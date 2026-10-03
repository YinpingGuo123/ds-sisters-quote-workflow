"""RFQ extraction: one structured-output LLM call, with a golden fallback.

Maps the model output (or fallback) into ``QuoteRequest`` field shapes. Does
not resolve catalog ids or persist cases - ``run_intake`` calls ``resolve``
after this.
"""

from __future__ import annotations

import os
from typing import Any

from quote_workflow.config import openai_model
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest
from quote_workflow.contracts.source import RfqSource
from quote_workflow.intake.fallback import fallback_extract
from quote_workflow.intake.output import LlmAddress, LlmExtractedRfq
from quote_workflow.intake.prompts import SYSTEM_PROMPT


def _to_address(raw: LlmAddress | None) -> Address | None:
    if raw is None or not raw.line1 or not raw.city or not raw.country:
        return None
    return Address(
        name=raw.name,
        line1=raw.line1,
        line2=raw.line2,
        city=raw.city,
        region=raw.region,
        postal_code=raw.postal_code,
        country=raw.country,
    )


def to_quote_request(extracted: LlmExtractedRfq, source_text: str) -> QuoteRequest:
    """Build a ``QuoteRequest`` from an extraction result."""
    return QuoteRequest(
        customer_name=extracted.customer_name,
        billing_address=_to_address(extracted.billing_address),
        shipping_address=_to_address(extracted.shipping_address),
        requested_delivery_date=extracted.requested_delivery_date,
        contract_months=extracted.contract_months,
        requested_discount_pct=extracted.requested_discount_pct,
        lines=[
            QuoteLine(
                product_name=line.product_name,
                quantity=line.quantity,
                requested_unit_price=line.requested_unit_price,
                competitor_price=line.competitor_price,
            )
            for line in extracted.lines
        ],
        source_text=source_text,
        notes=extracted.notes,
        clarification_questions=list(extracted.clarification_questions),
    )


def build_messages(source: RfqSource) -> list[dict[str, str]]:
    header = []
    if source.sender:
        header.append(f"From: {source.sender}")
    if source.subject:
        header.append(f"Subject: {source.subject}")
    prefix = "\n".join(header)
    body = source.body_text.strip()
    user = f"{prefix}\n\n{body}" if prefix else body
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _default_client() -> Any:
    from openai import OpenAI

    return OpenAI()


def llm_extract(source: RfqSource, client: Any | None = None, model: str | None = None) -> LlmExtractedRfq:
    """Call the LLM with structured output. Raises on failure."""
    model = model or openai_model()
    client = client or _default_client()
    completion = client.chat.completions.parse(
        model=model,
        messages=build_messages(source),
        response_format=LlmExtractedRfq,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("llm returned no parsed output")
    return parsed


def extract_from_source(
    source: RfqSource, *, client: Any | None = None, use_llm: bool | None = None
) -> LlmExtractedRfq:
    """Extract structured RFQ fields from one email.

    Uses the LLM when ``use_llm`` is true (default: ``OPENAI_API_KEY`` is set).
    Falls back to golden extractions for known inbox samples.
    """
    if use_llm is None:
        use_llm = bool(os.environ.get("OPENAI_API_KEY"))
    if use_llm:
        try:
            return llm_extract(source, client=client)
        except Exception:
            pass
    return fallback_extract(source.source_id)

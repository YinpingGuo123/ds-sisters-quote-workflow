"""The reviewer-summary call: one structured-output LLM request over the
pricing facts, validated, with a deterministic fallback.

What the LLM is for here - and only here: judgment and language for the
reviewer. Every number it may mention was computed by ``pricing``; the
statuses were decided there. ``summarize`` never raises: a missing API key,
a transport error, a parse failure, or a validation rejection all return the
fallback summary with ``rejected_reason`` set, so the case still completes.
"""

from __future__ import annotations

from typing import Any

from quote_workflow.config import openai_model
from quote_workflow.contracts.pricing import PricingDecision
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.review import ReviewerSummary
from quote_workflow.explain.facts import build_facts
from quote_workflow.explain.fallback import fallback_summary
from quote_workflow.explain.output import LlmSummary
from quote_workflow.explain.prompts import SYSTEM_PROMPT
from quote_workflow.explain.validate import validate_summary


def build_messages(
    request: QuoteRequest, pricing: PricingDecision, feedback: str | None = None
) -> list[dict[str, str]]:
    context = ""
    if request.source_text:
        context += f'\n\nCustomer\'s message:\n"""\n{request.source_text.strip()}\n"""'
    if request.notes:
        context += f"\n\nNotes from intake: {request.notes}"
    if feedback:
        # A reviewer asked for this summary to be rewritten. It steers the wording
        # only - the facts below are still the sole source of every number.
        context += (
            f"\n\nThe reviewer was not satisfied with the previous summary and asked for a revision:\n"
            f'"""\n{feedback.strip()}\n"""\n'
            "Address that request. Do not change, add or infer any number."
        )
    user = f"Pricing facts (do not change any number):\n\n{build_facts(request, pricing)}{context}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _default_client() -> Any:
    """An OpenAI client; imported lazily so the package works without the extra."""
    from openai import OpenAI

    return OpenAI()


def summarize(
    request: QuoteRequest,
    pricing: PricingDecision,
    client: Any | None = None,
    model: str | None = None,
    use_llm: bool = True,
    feedback: str | None = None,
) -> ReviewerSummary:
    """A ReviewerSummary for the case. Never raises.

    ``client`` is any object with ``chat.completions.parse`` (the OpenAI SDK
    or a test double); ``use_llm=False`` skips the call entirely. ``feedback``
    is a reviewer's complaint about a previous summary, used to steer the
    wording on a rewrite - it never relaxes validation.
    """
    if not use_llm or not pricing.lines:
        return fallback_summary(request, pricing, rejected_reason=None if not use_llm else "nothing priced")

    model = model or openai_model()
    try:
        client = client or _default_client()
        completion = client.chat.completions.parse(
            model=model, messages=build_messages(request, pricing, feedback), response_format=LlmSummary
        )
        candidate = completion.choices[0].message.parsed
    except Exception as exc:  # no API key, network, parse failure - all degrade to the fallback
        return fallback_summary(request, pricing, rejected_reason=f"llm call failed: {exc.__class__.__name__}")
    if candidate is None:
        return fallback_summary(request, pricing, rejected_reason="llm returned no parsed output")

    reason = validate_summary(candidate, build_facts(request, pricing), pricing)
    if reason is not None:
        return fallback_summary(request, pricing, rejected_reason=reason)

    return ReviewerSummary(
        summary=candidate.summary,
        rationale=candidate.rationale,
        warnings=candidate.warnings,
        attention_items=candidate.attention_items,
        draft_reply=candidate.draft_reply,
        generated_by="llm",
        model=model,
    )

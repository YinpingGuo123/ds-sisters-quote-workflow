"""RFQ extraction: golden fallback and LLM path with a fake client."""

from __future__ import annotations

from types import SimpleNamespace

from quote_workflow.contracts.enums import ResolutionStatus
from quote_workflow.intake import run_intake
from quote_workflow.intake.extract import extract_from_source, llm_extract, to_quote_request
from quote_workflow.intake.mailbox import fetch_new_rfqs
from quote_workflow.intake.output import LlmExtractedRfq, LlmLine


class FakeParseClient:
    def __init__(self, result):
        parse = self._parse
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=parse))
        self._result = result
        self.calls: list[dict] = []

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=self._result))])


def test_fallback_extracts_discount_email(built_db):
    source = next(s for s in fetch_new_rfqs() if s.source_id == "discount-within-policy.txt")
    request = run_intake(source, built_db)
    assert request.customer_status == ResolutionStatus.RESOLVED
    assert request.lines[0].product_status == ResolutionStatus.RESOLVED
    assert request.lines[0].quantity == 200
    assert request.requested_discount_pct == 15


def test_missing_quantity_becomes_needs_info_fields(built_db):
    source = next(s for s in fetch_new_rfqs() if s.source_id == "missing-quantity.txt")
    request = run_intake(source, built_db)
    assert request.lines[0].quantity is None
    assert request.clarification_questions


def test_llm_path_uses_structured_output():
    source = next(s for s in fetch_new_rfqs() if s.source_id == "competitor-price.txt")
    candidate = LlmExtractedRfq(
        customer_name="Jayanta Thakur",
        lines=[LlmLine(product_name="Pack of 12 action figures (variety)", quantity=30, competitor_price=13)],
    )
    client = FakeParseClient(candidate)
    extracted = llm_extract(source, client=client)
    request = to_quote_request(extracted, source.body_text)
    assert request.customer_name == "Jayanta Thakur"
    assert client.calls[0]["response_format"] is LlmExtractedRfq


def test_llm_failure_falls_back_to_golden():
    source = next(s for s in fetch_new_rfqs() if s.source_id == "active-deal.txt")
    client = FakeParseClient(RuntimeError("network down"))
    extracted = extract_from_source(source, client=client, use_llm=True)
    assert extracted.lines[0].quantity == 20

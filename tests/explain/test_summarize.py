"""The reviewer summary: fallback shape, grounding/leakage validation, and the
LLM path with an injected fake client (no network, no keys)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from quote_workflow.catalog.resolution import resolve
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest
from quote_workflow.explain.facts import build_facts
from quote_workflow.explain.fallback import fallback_summary
from quote_workflow.explain.output import LlmSummary
from quote_workflow.explain.summarize import build_messages, summarize
from quote_workflow.explain.validate import validate_summary
from quote_workflow.pricing.service import price_request

AS_OF = date(2026, 9, 5)
ADDRESS = Address(line1="1 Main St", city="Springfield", country="US")


class FakeParseClient:
    """Mimics ``client.chat.completions.parse``: returns ``result`` or raises it."""

    def __init__(self, result):
        self.calls: list[dict] = []
        parse = self._parse
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=parse))
        self._result = result

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=self._result))])


def _priced(built_db):
    request = resolve(
        built_db,
        QuoteRequest(
            customer_name="Eric Torres",
            billing_address=ADDRESS,
            shipping_address=ADDRESS,
            source_text="We need 10 periscopes at $12 each.",
            lines=[QuoteLine(product_name="Office cube periscope (Black)", quantity=10, requested_unit_price=12.0)],
        ),
    )
    return request, price_request(built_db, request, as_of_date=AS_OF)


def _candidate(**overrides) -> LlmSummary:
    base = dict(
        summary="The requested $12.00 is below what we can approve; a counter of $16.65 is recommended.",
        rationale=["Standard reseller pricing at list $18.50."],
        warnings=["Customer has an expired deal they may still expect."],
        attention_items=["Confirm the $16.65 counter."],
        draft_reply="Thanks for your request. We can offer the periscopes at $16.65 per unit.",
    )
    return LlmSummary(**{**base, **overrides})


def test_fallback_summary_is_built_from_the_decision(built_db):
    request, pricing = _priced(built_db)
    summary = fallback_summary(request, pricing)
    assert summary.generated_by == "fallback"
    assert summary.summary.startswith("1 line(s) priced for Eric Torres, total $166.50")
    assert summary.rationale[0].startswith("Line 1 (Office cube periscope (Black)): standard pricing")
    assert summary.warnings == pricing.warnings
    assert summary.attention_items == ["Line 1 (Office cube periscope (Black)): confirm the counter offer of $16.65."]
    assert summary.draft_reply is None


def test_facts_contain_the_numbers_the_llm_may_use(built_db):
    request, pricing = _priced(built_db)
    facts = build_facts(request, pricing)
    assert "$18.50" in facts and "$16.65" in facts and "$12.00" in facts
    assert "counter_recommended" in facts
    assert "engine rationale:" in facts
    messages = build_messages(request, pricing)
    assert messages[0]["role"] == "system" and "REVIEWER" in messages[0]["content"]
    assert "We need 10 periscopes" in messages[1]["content"]


def test_validation_rejects_numbers_not_in_facts_and_internal_leakage(built_db):
    request, pricing = _priced(built_db)
    facts = build_facts(request, pricing)
    assert validate_summary(_candidate(), facts, pricing) is None
    assert validate_summary(_candidate(summary="Go to $15.00."), facts, pricing).startswith(
        "dollar amount not in facts"
    )
    assert validate_summary(_candidate(rationale=["A 7.5% tier applies."]), facts, pricing).startswith(
        "percentage not in facts"
    )
    assert (
        validate_summary(_candidate(draft_reply="Our floor is $13.41."), facts, pricing)
        == "draft_reply leaks a margin-floor price"
    )
    assert "internal vocabulary" in validate_summary(_candidate(draft_reply="This needs escalation."), facts, pricing)


def test_summarize_accepts_a_valid_llm_answer(built_db):
    request, pricing = _priced(built_db)
    client = FakeParseClient(_candidate())
    summary = summarize(request, pricing, client=client, model="test-model")
    assert summary.generated_by == "llm" and summary.model == "test-model"
    assert summary.summary.startswith("The requested $12.00")
    assert summary.draft_reply.endswith("$16.65 per unit.")
    assert client.calls[0]["response_format"] is LlmSummary


def test_summarize_falls_back_on_rejection_and_on_errors(built_db):
    request, pricing = _priced(built_db)
    rejected = summarize(request, pricing, client=FakeParseClient(_candidate(summary="Offer $9.99.")), model="m")
    assert rejected.generated_by == "fallback" and rejected.rejected_reason.startswith("dollar amount not in facts")

    failed = summarize(request, pricing, client=FakeParseClient(RuntimeError("boom")), model="m")
    assert failed.generated_by == "fallback" and failed.rejected_reason == "llm call failed: RuntimeError"

    skipped = summarize(request, pricing, client=FakeParseClient(_candidate()), use_llm=False)
    assert skipped.generated_by == "fallback" and skipped.rejected_reason is None

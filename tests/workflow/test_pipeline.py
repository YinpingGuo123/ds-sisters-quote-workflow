"""End-to-end through the workflow with a temp catalog and a temp case store,
no LLM (use_llm=False) unless a fake client is injected."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from quote_workflow.catalog.resolution import resolve
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import CaseStatus, PricingStatus, ReviewAction
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.contracts.source import RfqSource
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import (
    apply_edit,
    apply_review,
    create_case,
    create_case_from_request,
    price_and_summarize,
    rerun,
    submit_request,
)
from quote_workflow.workflow.status import InvalidTransition, check_transition

AS_OF = date(2026, 9, 5)
ADDRESS = Address(
    name="Philip Walker", line1="418 Cedar Lane", city="Boise", region="ID", postal_code="83702", country="US"
)


@pytest.fixture
def store(tmp_path: Path):
    s = SqliteCaseStore(tmp_path / "cases.db")
    try:
        yield s
    finally:
        s.close()


def _complete_request(built_db) -> QuoteRequest:
    return resolve(
        built_db,
        QuoteRequest(
            customer_name="Philip Walker",
            billing_address=ADDRESS,
            shipping_address=ADDRESS,
            requested_delivery_date=date(2026, 10, 15),
            lines=[QuoteLine(product_name="Superhero action jacket (Blue) M", quantity=10)],
        ),
    )


def _decision(action: ReviewAction, comment: str | None = None) -> ReviewDecision:
    return ReviewDecision(action=action, reviewer="Sarah", comment=comment, decided_at=datetime.now(UTC))


def test_complete_request_is_priced_summarized_and_ready(built_db, store):
    case = create_case_from_request(
        store, built_db, _complete_request(built_db), case_id="Q-1", as_of_date=AS_OF, use_llm=False
    )

    assert case.status == CaseStatus.READY_FOR_REVIEW
    assert case.assigned_to == "Sarah"
    assert case.pricing.status == PricingStatus.APPROVED
    assert case.pricing.total_quoted_value == pytest.approx(300.0)
    assert case.summary.generated_by == "fallback"
    assert [e.stage for e in case.events] == ["intake", "intake", "pricing", "explain", "pipeline"]
    assert (
        case.events[-1].from_status == CaseStatus.RECEIVED and case.events[-1].to_status == CaseStatus.READY_FOR_REVIEW
    )

    # persisted, not just returned
    assert store.get("Q-1").status == CaseStatus.READY_FOR_REVIEW


def test_incomplete_request_waits_in_needs_info_then_completes(built_db, store):
    partial = _complete_request(built_db).model_copy(
        update={"shipping_address": None, "clarification_questions": ["Where should it ship?"]}
    )
    case = create_case_from_request(store, built_db, partial, case_id="Q-2", as_of_date=AS_OF, use_llm=False)
    assert case.status == CaseStatus.NEEDS_INFO
    assert case.pricing is None
    assert "shipping address missing" in case.events[-1].message and "Where should it ship?" in case.events[-1].message

    completed = submit_request(
        store,
        built_db,
        "Q-2",
        partial.model_copy(update={"shipping_address": ADDRESS}),
        as_of_date=AS_OF,
        use_llm=False,
    )
    assert completed.status == CaseStatus.READY_FOR_REVIEW
    assert completed.pricing is not None


def test_unresolved_product_is_needs_info_not_failed(built_db, store):
    request = resolve(
        built_db,
        QuoteRequest(
            customer_name="Philip Walker",
            billing_address=ADDRESS,
            shipping_address=ADDRESS,
            lines=[QuoteLine(product_name="Deluxe Rocket Backpack", quantity=5)],
        ),
    )
    case = create_case_from_request(store, built_db, request, case_id="Q-3", use_llm=False)
    assert case.status == CaseStatus.NEEDS_INFO
    assert "not found" in case.events[-1].message


def test_approve_builds_quotation_and_reject_does_not(built_db, store):
    create_case_from_request(
        store, built_db, _complete_request(built_db), case_id="Q-4", as_of_date=AS_OF, use_llm=False
    )
    approved = apply_review(store, "Q-4", _decision(ReviewAction.APPROVE, "Looks good"), today=AS_OF)
    assert approved.status == CaseStatus.APPROVED
    assert approved.quotation.quote_number == "Q-2026-Q-4"
    assert approved.quotation.valid_until == date(2026, 10, 5)
    assert approved.quotation.total == pytest.approx(300.0)
    assert approved.quotation.shipping_address == ADDRESS
    assert "Superhero action jacket (Blue) M" in approved.quotation.body
    assert approved.quotation.notes == "Looks good"
    assert approved.events[-1].message.endswith("quotation Q-2026-Q-4 generated")

    create_case_from_request(
        store, built_db, _complete_request(built_db), case_id="Q-5", as_of_date=AS_OF, use_llm=False
    )
    rejected = apply_review(store, "Q-5", _decision(ReviewAction.REJECT, "Customer on credit hold"))
    assert rejected.status == CaseStatus.REJECTED and rejected.quotation is None


def test_request_info_moves_back_to_needs_info_and_terminal_cases_refuse_review(built_db, store):
    create_case_from_request(
        store, built_db, _complete_request(built_db), case_id="Q-6", as_of_date=AS_OF, use_llm=False
    )
    case = apply_review(store, "Q-6", _decision(ReviewAction.REQUEST_INFO, "Please confirm the delivery date"))
    assert case.status == CaseStatus.NEEDS_INFO
    with pytest.raises(ValueError):
        apply_review(store, "Q-6", _decision(ReviewAction.APPROVE))

    create_case_from_request(
        store, built_db, _complete_request(built_db), case_id="Q-7", as_of_date=AS_OF, use_llm=False
    )
    apply_review(store, "Q-7", _decision(ReviewAction.APPROVE), today=AS_OF)
    with pytest.raises(ValueError):
        apply_review(store, "Q-7", _decision(ReviewAction.REJECT))


def test_stage_error_marks_case_failed_and_rerun_recovers(built_db, store, monkeypatch):
    import quote_workflow.workflow.pipeline as pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(pipeline, "price_request", boom)
    case = create_case_from_request(store, built_db, _complete_request(built_db), case_id="Q-8", use_llm=False)
    assert case.status == CaseStatus.FAILED
    assert case.events[-1].level == "error" and "engine exploded" in case.events[-1].message

    monkeypatch.undo()
    recovered = rerun(store, built_db, "Q-8", as_of_date=AS_OF, use_llm=False)
    assert recovered.status == CaseStatus.READY_FOR_REVIEW


def test_case_with_source_keeps_the_original_rfq(store):
    source = RfqSource(
        source_id="mail-1",
        received_at=datetime.now(UTC),
        sender="alex@tailspin.example",
        subject="Order",
        body_text="20 launchers please",
    )
    case = create_case(store, source=source, assigned_to="John")
    assert case.status == CaseStatus.RECEIVED and case.assigned_to == "John"
    assert store.get(case.case_id).source.body_text == "20 launchers please"


# --- reviewer edits ------------------------------------------------------------


def test_edit_completes_a_needs_info_case_prices_it_and_persists(built_db, store, tmp_path):
    partial = _complete_request(built_db).model_copy(update={"shipping_address": None})
    case = create_case_from_request(store, built_db, partial, case_id="Q-E1", as_of_date=AS_OF, use_llm=False)
    assert case.status == CaseStatus.NEEDS_INFO

    edited = apply_edit(
        store,
        built_db,
        "Q-E1",
        partial.model_copy(update={"shipping_address": ADDRESS}),
        editor="Sarah",
        as_of_date=AS_OF,
        use_llm=False,
    )

    assert edited.status == CaseStatus.READY_FOR_REVIEW
    assert edited.pricing is not None
    assert edited.request.shipping_address == ADDRESS
    edit_events = [e for e in edited.events if e.stage == "review"]
    assert len(edit_events) == 1
    assert edit_events[0].message == "Sarah edited the request: shipping address"

    # survives a fresh connection to the same database file
    reopened = SqliteCaseStore(tmp_path / "cases.db")
    try:
        assert reopened.get("Q-E1").status == CaseStatus.READY_FOR_REVIEW
    finally:
        reopened.close()


def test_edit_that_changes_a_quantity_reprices(built_db, store):
    request = _complete_request(built_db)
    create_case_from_request(store, built_db, request, case_id="Q-E2", as_of_date=AS_OF, use_llm=False)

    doubled = request.model_copy(update={"lines": [request.lines[0].model_copy(update={"quantity": 20})]})
    edited = apply_edit(store, built_db, "Q-E2", doubled, editor="Sarah", as_of_date=AS_OF, use_llm=False)

    # list price is $30.00/unit and the volume ladder starts at 50 units, so 20 x $30.00
    assert edited.status == CaseStatus.READY_FOR_REVIEW
    assert edited.pricing.lines[0].quantity == 20
    assert edited.pricing.total_quoted_value == pytest.approx(600.0)
    assert edited.events[-1].to_status == CaseStatus.READY_FOR_REVIEW


def test_edit_without_changes_records_nothing(built_db, store):
    request = _complete_request(built_db)
    case = create_case_from_request(store, built_db, request, case_id="Q-E3", as_of_date=AS_OF, use_llm=False)
    before = len(case.events)

    unchanged = apply_edit(store, built_db, "Q-E3", request, editor="Sarah", as_of_date=AS_OF, use_llm=False)

    assert len(unchanged.events) == before
    assert unchanged.status == CaseStatus.READY_FOR_REVIEW


def test_edit_is_refused_once_a_case_is_decided(built_db, store):
    request = _complete_request(built_db)
    create_case_from_request(store, built_db, request, case_id="Q-E4", as_of_date=AS_OF, use_llm=False)
    apply_review(store, "Q-E4", _decision(ReviewAction.APPROVE), today=AS_OF)

    with pytest.raises(ValueError, match="approved"):
        apply_edit(store, built_db, "Q-E4", request, editor="Sarah", use_llm=False)


@pytest.mark.parametrize("action", [ReviewAction.APPROVE, ReviewAction.REJECT])
def test_a_decided_case_keeps_its_pricing_record_untouched(built_db, store, action):
    """Regression: re-running a decided case used to overwrite its PricingDecision
    and append events before the transition check refused it, so an approved case
    could end up showing a different price than the quotation that was sent."""
    case_id = f"Q-final-{action.value}"
    create_case_from_request(
        store, built_db, _complete_request(built_db), case_id=case_id, as_of_date=AS_OF, use_llm=False
    )
    decided = apply_review(store, case_id, _decision(action), today=AS_OF)
    priced_at, events = decided.pricing.priced_at, len(decided.events)

    for attempt in (
        lambda: rerun(store, built_db, case_id, as_of_date=AS_OF, use_llm=False),
        lambda: price_and_summarize(store, built_db, case_id, as_of_date=AS_OF, use_llm=False),
        lambda: submit_request(store, built_db, case_id, decided.request, as_of_date=AS_OF, use_llm=False),
    ):
        with pytest.raises(InvalidTransition, match="are final"):
            attempt()

    after = store.get(case_id)
    assert after.status == decided.status
    assert after.pricing.priced_at == priced_at, "the stored PricingDecision was replaced"
    assert len(after.events) == events, "a refused re-run still wrote to the audit trail"
    if action == ReviewAction.APPROVE:
        assert after.quotation.total == after.pricing.total_quoted_value


def test_transition_table():
    check_transition(CaseStatus.RECEIVED, CaseStatus.NEEDS_INFO)
    check_transition(CaseStatus.READY_FOR_REVIEW, CaseStatus.APPROVED)
    with pytest.raises(InvalidTransition):
        check_transition(CaseStatus.APPROVED, CaseStatus.READY_FOR_REVIEW)
    with pytest.raises(InvalidTransition):
        check_transition(CaseStatus.RECEIVED, CaseStatus.APPROVED)

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
from quote_workflow.workflow import apply_review, create_case, create_case_from_request, rerun, submit_request
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
    assert "Superhero action jacket (Blue) M" in approved.quotation.body_markdown
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


def test_transition_table():
    check_transition(CaseStatus.RECEIVED, CaseStatus.NEEDS_INFO)
    check_transition(CaseStatus.READY_FOR_REVIEW, CaseStatus.APPROVED)
    with pytest.raises(InvalidTransition):
        check_transition(CaseStatus.APPROVED, CaseStatus.READY_FOR_REVIEW)
    with pytest.raises(InvalidTransition):
        check_transition(CaseStatus.RECEIVED, CaseStatus.APPROVED)

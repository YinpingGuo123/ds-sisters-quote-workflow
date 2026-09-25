"""Rework: a reviewer sends a case back to one of our own stages, it parks in
REWORK_REQUESTED where it is discoverable, and running it returns the case to
review with fresh numbers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from quote_workflow.catalog.resolution import resolve
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import CaseStatus, ReviewAction, ReworkTarget
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import apply_review, create_case_from_request, request_rework, run_rework
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


def _ready_case(built_db, store, case_id: str):
    request = resolve(
        built_db,
        QuoteRequest(
            customer_name="Philip Walker",
            billing_address=ADDRESS,
            shipping_address=ADDRESS,
            lines=[QuoteLine(product_name="Superhero action jacket (Blue) M", quantity=10)],
        ),
    )
    return create_case_from_request(store, built_db, request, case_id=case_id, as_of_date=AS_OF, use_llm=False)


def test_requesting_rework_parks_the_case_and_records_target_and_reason(built_db, store):
    _ready_case(built_db, store, "Q-R1")

    case = request_rework(store, "Q-R1", ReworkTarget.EXPLAIN, "The summary buries the margin", "Sarah")

    assert case.status == CaseStatus.REWORK_REQUESTED
    assert case.rework.target == ReworkTarget.EXPLAIN
    assert case.rework.reason == "The summary buries the margin"
    assert case.rework.requested_by == "Sarah" and case.rework.resolved_at is None
    assert case.events[-1].message == "Sarah requested explain rework: The summary buries the margin"
    assert case.events[-1].to_status == CaseStatus.REWORK_REQUESTED


def test_a_parked_case_is_discoverable_by_status_alone(built_db, store):
    _ready_case(built_db, store, "Q-R2")
    _ready_case(built_db, store, "Q-R3")
    request_rework(store, "Q-R3", ReworkTarget.PRICING, "Re-price against the new policy", "Sarah")

    # this query is the whole discovery mechanism - no work-item table
    waiting = store.list(status=CaseStatus.REWORK_REQUESTED)

    assert [case.case_id for case in waiting] == ["Q-R3"]
    assert waiting[0].rework.target == ReworkTarget.PRICING


def test_running_rework_returns_the_case_to_review_and_resolves_the_request(built_db, store):
    _ready_case(built_db, store, "Q-R4")
    request_rework(store, "Q-R4", ReworkTarget.PRICING, "Re-price", "Sarah")

    case = run_rework(store, built_db, "Q-R4", as_of_date=AS_OF, use_llm=False)

    assert case.status == CaseStatus.READY_FOR_REVIEW
    assert case.rework.resolved_at is not None
    assert case.pricing.total_quoted_value == pytest.approx(300.0)  # 10 units x $30.00 list, below every ladder
    assert case.events[-1].message == "pricing rework completed"
    assert not store.list(status=CaseStatus.REWORK_REQUESTED)


def test_explain_rework_passes_the_reviewers_reason_to_the_summary(built_db, store):
    _ready_case(built_db, store, "Q-R5")
    request_rework(store, "Q-R5", ReworkTarget.EXPLAIN, "Say plainly it is within policy", "Sarah")
    seen: dict[str, object] = {}

    class FakeClient:
        class chat:  # noqa: N801 - mirrors the OpenAI client shape
            class completions:
                @staticmethod
                def parse(*, model, messages, response_format):
                    seen["messages"] = messages
                    raise RuntimeError("stop after capturing the prompt")

    case = run_rework(store, built_db, "Q-R5", as_of_date=AS_OF, llm_client=FakeClient(), use_llm=True)

    prompt = seen["messages"][-1]["content"]
    assert "Say plainly it is within policy" in prompt
    assert "Do not change, add or infer any number." in prompt
    # the call was made to fail, so the case still completes on the fallback
    assert case.status == CaseStatus.READY_FOR_REVIEW
    assert case.summary.generated_by == "fallback"


def test_a_case_awaiting_rework_cannot_be_approved(built_db, store):
    _ready_case(built_db, store, "Q-R6")
    request_rework(store, "Q-R6", ReworkTarget.EXPLAIN, "Reword it", "Sarah")

    decision = ReviewDecision(action=ReviewAction.APPROVE, reviewer="Sarah", decided_at=datetime.now(UTC))
    with pytest.raises(ValueError, match="rework_requested"):
        apply_review(store, "Q-R6", decision)
    with pytest.raises(InvalidTransition):
        check_transition(CaseStatus.REWORK_REQUESTED, CaseStatus.APPROVED)


def test_rework_is_refused_where_there_is_nothing_to_rework(built_db, store):
    _ready_case(built_db, store, "Q-R7")
    with pytest.raises(ValueError, match="no open rework"):
        run_rework(store, built_db, "Q-R7", use_llm=False)

    request_rework(store, "Q-R7", ReworkTarget.PRICING, "Re-price", "Sarah")
    with pytest.raises(ValueError, match="only a case in review"):
        request_rework(store, "Q-R7", ReworkTarget.PRICING, "again", "Sarah")

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quote_workflow.contracts.case import CaseEvent, QuoteCase
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.storage.sqlite_store import SqliteCaseStore

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _case(
    case_id: str = "C-1", status: CaseStatus = CaseStatus.RECEIVED, assigned_to: str | None = "Sarah"
) -> QuoteCase:
    return QuoteCase(
        case_id=case_id,
        status=status,
        created_at=NOW,
        updated_at=NOW,
        assigned_to=assigned_to,
        request=QuoteRequest(customer_name="Acme"),
    )


def _event(message: str, to_status: CaseStatus | None = None) -> CaseEvent:
    return CaseEvent(at=NOW, stage="test", message=message, to_status=to_status)


@pytest.fixture
def store(tmp_path: Path):
    s = SqliteCaseStore(tmp_path / "cases.db")
    try:
        yield s
    finally:
        s.close()


def test_create_then_get_round_trips_case_and_first_event(store):
    created = store.create(_case(), _event("received", CaseStatus.RECEIVED))
    assert created.case_id == "C-1"
    assert [e.message for e in created.events] == ["received"]

    fetched = store.get("C-1")
    assert fetched.request.customer_name == "Acme"
    assert fetched.events == created.events


def test_get_unknown_raises_key_error(store):
    with pytest.raises(KeyError):
        store.get("nope")


def test_save_updates_state_and_appends_event_in_order(store):
    store.create(_case(), _event("received"))
    case = store.get("C-1")
    case.status = CaseStatus.READY_FOR_REVIEW
    store.save(case, _event("priced", CaseStatus.READY_FOR_REVIEW))
    store.save(case)  # no event: state only

    fetched = store.get("C-1")
    assert fetched.status == CaseStatus.READY_FOR_REVIEW
    assert [e.message for e in fetched.events] == ["received", "priced"]
    assert fetched.events[1].to_status == CaseStatus.READY_FOR_REVIEW


def test_save_unknown_case_raises(store):
    with pytest.raises(KeyError):
        store.save(_case("ghost"))


def test_list_filters_by_status_and_assignee_and_omits_events(store):
    store.create(_case("A", CaseStatus.READY_FOR_REVIEW, "Sarah"), _event("a"))
    store.create(_case("B", CaseStatus.NEEDS_INFO, "Sarah"), _event("b"))
    store.create(_case("C", CaseStatus.READY_FOR_REVIEW, "John"), _event("c"))

    assert {c.case_id for c in store.list()} == {"A", "B", "C"}
    assert [c.case_id for c in store.list(status=CaseStatus.READY_FOR_REVIEW, assigned_to="Sarah")] == ["A"]
    assert {c.case_id for c in store.list(assigned_to="Sarah")} == {"A", "B"}
    assert all(c.events == [] for c in store.list())


def test_events_are_not_duplicated_into_the_json_blob(store):
    store.create(_case(), _event("received"))
    raw = store._conn.execute("SELECT case_json FROM cases WHERE case_id = 'C-1'").fetchone()[0]
    assert '"events"' not in raw

"""The intake -> workflow contract, checked against every intake implementation.

An implementation is a module exposing
    fetch_new_rfqs() -> list[RfqSource]
    run_intake(source, conn) -> QuoteRequest
and the portal's "Check inbox" button calls exactly those two. Today the only
one is the mock (``demo_inbox``); the real intake joins ``IMPLEMENTATIONS``
with its LLM client and mailbox mocked, and must pass the same checks.

Why each check exists:
- stable ``source_id``s: the store dedups on them; unstable ids duplicate cases
- resolution statuses set: a product name left at the default MISSING is
  reported as "product not specified" - a misleading NEEDS_INFO, not an error
- resolved ids exist: pricing looks them up and fails the case otherwise
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quote_workflow import demo_inbox, intake
from quote_workflow.catalog.repository import get_customer_by_id, get_product_by_id
from quote_workflow.contracts.enums import CaseStatus, ResolutionStatus
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import ingest_sources

IMPLEMENTATIONS = [
    pytest.param(demo_inbox, id="demo_inbox"),
    pytest.param(intake, id="intake"),
]


@pytest.fixture
def store(tmp_path: Path):
    s = SqliteCaseStore(tmp_path / "cases.db")
    try:
        yield s
    finally:
        s.close()


@pytest.mark.parametrize("intake", IMPLEMENTATIONS)
def test_source_ids_are_unique_and_stable(intake):
    first = [source.source_id for source in intake.fetch_new_rfqs()]
    second = [source.source_id for source in intake.fetch_new_rfqs()]

    assert first, "the mailbox fixture should hold at least one RFQ"
    assert len(first) == len(set(first))
    assert first == second


@pytest.mark.parametrize("intake", IMPLEMENTATIONS)
def test_run_intake_returns_a_resolved_quote_request(intake, built_db):
    for source in intake.fetch_new_rfqs():
        request = intake.run_intake(source, built_db)

        assert isinstance(request, QuoteRequest), source.source_id
        if request.customer_name:
            assert request.customer_status != ResolutionStatus.MISSING, f"{source.source_id}: customer not resolved"
        if request.customer_status == ResolutionStatus.RESOLVED:
            assert get_customer_by_id(built_db, request.customer_id) is not None, source.source_id
        for line in request.lines:
            if line.product_name:
                assert line.product_status != ResolutionStatus.MISSING, f"{source.source_id}: '{line.product_name}'"
            if line.product_status == ResolutionStatus.RESOLVED:
                assert get_product_by_id(built_db, line.product_id) is not None, source.source_id


@pytest.mark.parametrize("intake", IMPLEMENTATIONS)
def test_the_inbox_runs_through_the_workflow_without_failures(intake, store, built_db):
    created = ingest_sources(store, built_db, intake.fetch_new_rfqs(), intake.run_intake, use_llm=False)

    assert created
    assert [case.case_id for case in created if case.status == CaseStatus.FAILED] == []
    assert ingest_sources(store, built_db, intake.fetch_new_rfqs(), intake.run_intake, use_llm=False) == []

"""The composer: the one place the stage order is written down.

    create_case_from_request / create_case_from_source
        → submit_request            (complete? else NEEDS_INFO)
            → price_and_summarize   (pricing, then reviewer summary, then READY_FOR_REVIEW)

Pricing is complete and final before the LLM is contacted; the summary can
only degrade to the deterministic fallback, never change a number or a
status. Any unhandled exception in a stage marks the case FAILED with the
error in its events instead of leaving it half-processed.

No pricing math, no prompt text, no SQL here - see ``pricing``, ``explain``,
``storage``. Intake hands its result to ``submit_request``.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, date, datetime
from typing import Any

from quote_workflow.config import default_reviewer
from quote_workflow.contracts.case import CaseEvent, QuoteCase
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.source import RfqSource
from quote_workflow.contracts.store import CaseStore
from quote_workflow.explain.summarize import summarize
from quote_workflow.pricing.policy import PricingPolicy
from quote_workflow.pricing.service import price_request
from quote_workflow.workflow.status import check_transition


def _now() -> datetime:
    return datetime.now(UTC)


def new_case_id() -> str:
    return f"Q-{uuid.uuid4().hex[:6].upper()}"


def _event(
    stage: str, message: str, case: QuoteCase, to_status: CaseStatus | None = None, level: str = "info"
) -> CaseEvent:
    return CaseEvent(
        at=_now(),
        stage=stage,
        message=message,
        level=level,
        from_status=case.status if to_status is not None else None,
        to_status=to_status,
    )


def _transition(
    store: CaseStore, case: QuoteCase, target: CaseStatus, stage: str, message: str, level: str = "info"
) -> QuoteCase:
    check_transition(case.status, target)
    event = _event(stage, message, case, to_status=target, level=level)
    case.status = target
    case.updated_at = _now()
    store.save(case, event)
    return store.get(case.case_id)  # re-read so the returned case carries the full event history


# --- creation ------------------------------------------------------------------


def create_case(
    store: CaseStore, source: RfqSource | None = None, case_id: str | None = None, assigned_to: str | None = None
) -> QuoteCase:
    """A new RECEIVED case, optionally carrying the raw RFQ."""
    now = _now()
    case = QuoteCase(
        case_id=case_id or new_case_id(),
        status=CaseStatus.RECEIVED,
        created_at=now,
        updated_at=now,
        assigned_to=assigned_to or default_reviewer(),
        source=source,
    )
    origin = f"from {source.source_id}" if source else "from a structured request"
    return store.create(case, _event("intake", f"case created {origin}", case, to_status=CaseStatus.RECEIVED))


def create_case_from_request(
    store: CaseStore,
    conn: sqlite3.Connection,
    request: QuoteRequest,
    *,
    case_id: str | None = None,
    assigned_to: str | None = None,
    source: RfqSource | None = None,
    **run_options: Any,
) -> QuoteCase:
    """Create a case and run it through submit_request in one go (seeding, tests, evaluation)."""
    case = create_case(store, source=source, case_id=case_id, assigned_to=assigned_to)
    return submit_request(store, conn, case.case_id, request, **run_options)


# --- the seam ------------------------------------------------------------------


def submit_request(
    store: CaseStore,
    conn: sqlite3.Connection,
    case_id: str,
    request: QuoteRequest,
    **run_options: Any,
) -> QuoteCase:
    """Attach a (possibly updated) request to the case and continue.

    THE integration point: intake calls it with its extraction, the seed script
    with a sample, a future "provide information" form with the completed
    request. Incomplete → NEEDS_INFO with what is missing in the event;
    complete → priced and summarized.
    """
    case = store.get(case_id)
    case.request = request
    missing = request.missing_fields()
    if missing:
        detail = "; ".join(missing)
        if request.clarification_questions:
            detail += " | questions: " + " ".join(request.clarification_questions)
        return _transition(
            store, case, CaseStatus.NEEDS_INFO, "intake", f"request incomplete: {detail}", level="warning"
        )

    store.save(case, _event("intake", "request complete", case))
    return price_and_summarize(store, conn, case_id, **run_options)


def price_and_summarize(
    store: CaseStore,
    conn: sqlite3.Connection,
    case_id: str,
    *,
    policy: PricingPolicy | None = None,
    as_of_date: date | None = None,
    llm_client: Any | None = None,
    use_llm: bool = True,
    reviewer_feedback: str | None = None,
) -> QuoteCase:
    """Pricing first (deterministic, final), then the reviewer summary, then READY_FOR_REVIEW.

    ``reviewer_feedback`` is passed through to ``explain`` on a rework, so the
    rewritten summary answers the reviewer. It cannot affect a price: pricing
    has already run and is final by the time the summary is requested.
    """
    case = store.get(case_id)
    if case.request is None:
        raise ValueError(f"case {case_id} has no request to price")
    if not case.request.is_complete:
        return submit_request(store, conn, case_id, case.request)

    try:
        case.pricing = price_request(conn, case.request, policy=policy, as_of_date=as_of_date)
        store.save(
            case,
            _event(
                "pricing",
                f"priced {len(case.pricing.lines)} line(s): status {case.pricing.status.value}, "
                f"total ${case.pricing.total_quoted_value:,.2f} (policy {case.pricing.policy_version})",
                case,
                level="warning" if case.pricing.warnings else "info",
            ),
        )

        case.summary = summarize(
            case.request, case.pricing, client=llm_client, use_llm=use_llm, feedback=reviewer_feedback
        )
        if case.summary.generated_by == "llm":
            message = f"reviewer summary generated by {case.summary.model}"
        else:
            message = "reviewer summary: deterministic fallback" + (
                f" ({case.summary.rejected_reason})" if case.summary.rejected_reason else ""
            )
        store.save(case, _event("explain", message, case))
    except Exception as exc:
        return _transition(
            store, case, CaseStatus.FAILED, "pipeline", f"{exc.__class__.__name__}: {exc}", level="error"
        )

    return _transition(store, case, CaseStatus.READY_FOR_REVIEW, "pipeline", "ready for review")


def rerun(store: CaseStore, conn: sqlite3.Connection, case_id: str, **run_options: Any) -> QuoteCase:
    """Re-run a FAILED (or already reviewed-ready) case from its stored request."""
    case = store.get(case_id)
    if case.status == CaseStatus.FAILED:
        _transition(store, case, CaseStatus.RECEIVED, "pipeline", "re-run requested")
    if case.request is None:
        raise ValueError(f"case {case_id} has no request to re-run")
    return submit_request(store, conn, case_id, case.request, **run_options)

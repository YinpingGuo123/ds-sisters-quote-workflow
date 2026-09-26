"""Human decisions on a case. The portal calls ``apply_review`` and
``apply_edit``; it never changes a status itself.

APPROVE also builds the Quotation, so "approved" always means "there is a
quotation to send". REQUEST_INFO moves the case back to NEEDS_INFO with the
reviewer's question in the events; a completed request comes back through
``pipeline.submit_request``.

``apply_edit`` is the reviewer's correction path: it records who changed what
and then hands the corrected request to that same ``submit_request`` seam, so
a case that is still incomplete waits in NEEDS_INFO and a case that is now
complete is re-priced. It decides no status of its own.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from quote_workflow.contracts.case import CaseEvent, QuoteCase
from quote_workflow.contracts.enums import CaseStatus, ReviewAction, ReworkTarget
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.review import ReviewDecision, ReworkRequest
from quote_workflow.contracts.store import CaseStore
from quote_workflow.quotation.render import build_quotation
from quote_workflow.workflow.pipeline import price_and_summarize, submit_request
from quote_workflow.workflow.status import REVIEW_OUTCOME, check_transition

# A reviewer may correct a case that is waiting for information or sitting in
# review. Approved/rejected cases are history, and a FAILED case has no usable
# request to edit - it goes through ``pipeline.rerun`` instead.
EDITABLE_STATUSES = (CaseStatus.NEEDS_INFO, CaseStatus.READY_FOR_REVIEW)

# Fields the portal's edit dialog may change; used only to describe the edit in
# the event log. Prices are deliberately absent - no price overrides in the MVP.
_EDITED_FIELDS = ("billing_address", "shipping_address", "requested_delivery_date", "contract_months")


def apply_review(store: CaseStore, case_id: str, decision: ReviewDecision, today: date | None = None) -> QuoteCase:
    case = store.get(case_id)
    if case.status != CaseStatus.READY_FOR_REVIEW:
        raise ValueError(f"case {case_id} is {case.status.value}, not ready for review")
    # Enforced here rather than on the model, so decisions stored before the
    # field existed still load; only new rejections must carry a reason.
    if decision.action == ReviewAction.REJECT and decision.rejection_reason is None:
        raise ValueError("a rejection needs a reason")
    target = REVIEW_OUTCOME[decision.action]
    check_transition(case.status, target)

    case.review = decision
    if decision.action == ReviewAction.APPROVE:
        case.quotation = build_quotation(case, today=today)

    now = datetime.now(UTC)
    message = f"{decision.reviewer}: {decision.action.value}"
    if decision.rejection_reason:
        message += f" ({decision.rejection_reason.value})"
    message += f" - {decision.comment}" if decision.comment else ""
    if case.quotation is not None:
        message += f" | quotation {case.quotation.quote_number} generated"
    event = CaseEvent(at=now, stage="review", message=message, from_status=case.status, to_status=target)

    case.status = target
    case.updated_at = now
    store.save(case, event)
    return store.get(case_id)


def _describe_edit(before: QuoteRequest | None, after: QuoteRequest) -> list[str]:
    """Which parts of the request the reviewer actually changed."""
    if before is None:
        return ["request"]
    changed = [name.replace("_", " ") for name in _EDITED_FIELDS if getattr(before, name) != getattr(after, name)]
    if [line.quantity for line in before.lines] != [line.quantity for line in after.lines]:
        changed.append("quantities")
    return changed


def apply_edit(
    store: CaseStore,
    conn: sqlite3.Connection,
    case_id: str,
    request: QuoteRequest,
    editor: str,
    note: str | None = None,
    **run_options: Any,
) -> QuoteCase:
    """Record a reviewer's correction, then re-run the standard seam.

    Returns the case unchanged when nothing was actually edited, so an
    accidental save costs neither an event nor a re-price.
    """
    case = store.get(case_id)
    if case.status not in EDITABLE_STATUSES:
        allowed = " or ".join(status.value for status in EDITABLE_STATUSES)
        raise ValueError(f"case {case_id} is {case.status.value}; only a case in {allowed} can be edited")

    changed = _describe_edit(case.request, request)
    if not changed and not note:
        return case

    message = f"{editor} edited the request"
    if changed:
        message += ": " + ", ".join(changed)
    if note:
        message += f" - {note}"
    store.save(case, CaseEvent(at=datetime.now(UTC), stage="review", message=message))

    # submit_request re-reads the case, so the outcome is decided by the one
    # completeness rule: still incomplete -> NEEDS_INFO, complete -> re-priced.
    return submit_request(store, conn, case_id, request, **run_options)


# --- rework --------------------------------------------------------------------


def request_rework(
    store: CaseStore, case_id: str, target: ReworkTarget, reason: str, requested_by: str
) -> QuoteCase:
    """Send a case back to one of our own stages. Does not do the work.

    Deliberately two-step: the case parks in REWORK_REQUESTED where the queue
    can show it and a reviewer cannot approve it, until someone - the portal or
    ``scripts/run_rework.py`` - calls ``run_rework``.
    """
    case = store.get(case_id)
    if case.status != CaseStatus.READY_FOR_REVIEW:
        raise ValueError(f"case {case_id} is {case.status.value}; only a case in review can be sent for rework")
    check_transition(case.status, CaseStatus.REWORK_REQUESTED)

    now = datetime.now(UTC)
    case.rework = ReworkRequest(target=target, reason=reason, requested_by=requested_by, requested_at=now)
    event = CaseEvent(
        at=now,
        stage="rework",
        message=f"{requested_by} requested {target.value} rework: {reason}",
        level="warning",
        from_status=case.status,
        to_status=CaseStatus.REWORK_REQUESTED,
    )
    case.status = CaseStatus.REWORK_REQUESTED
    case.updated_at = now
    store.save(case, event)
    return store.get(case_id)


def run_rework(store: CaseStore, conn: sqlite3.Connection, case_id: str, **run_options: Any) -> QuoteCase:
    """Carry out an open rework request and return the case to review.

    Both targets re-run the same seam - pricing, then the summary - so a
    reworked case can never carry a stale number. An EXPLAIN request also hands
    the reviewer's reason to ``explain`` so the new summary answers it.
    """
    case = store.get(case_id)
    if case.status != CaseStatus.REWORK_REQUESTED or case.rework is None:
        raise ValueError(f"case {case_id} has no open rework request")

    target = case.rework.target
    feedback = case.rework.reason if target == ReworkTarget.EXPLAIN else None
    reworked = price_and_summarize(store, conn, case_id, reviewer_feedback=feedback, **run_options)
    if reworked.status != CaseStatus.READY_FOR_REVIEW or reworked.rework is None:
        return reworked  # the re-run failed or fell back to NEEDS_INFO; the request stays open

    now = datetime.now(UTC)
    reworked.rework = reworked.rework.model_copy(update={"resolved_at": now})
    reworked.updated_at = now
    store.save(reworked, CaseEvent(at=now, stage="rework", message=f"{target.value} rework completed"))
    return store.get(case_id)

"""Human decisions on a case. The portal calls ``apply_review``; it never
changes a status itself.

APPROVE also builds the Quotation, so "approved" always means "there is a
quotation to send". REQUEST_INFO moves the case back to NEEDS_INFO with the
reviewer's question in the events; a completed request comes back through
``pipeline.submit_request``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from quote_workflow.contracts.case import CaseEvent, QuoteCase
from quote_workflow.contracts.enums import CaseStatus, ReviewAction
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.contracts.store import CaseStore
from quote_workflow.quotation.render import build_quotation
from quote_workflow.workflow.status import REVIEW_OUTCOME, check_transition


def apply_review(store: CaseStore, case_id: str, decision: ReviewDecision, today: date | None = None) -> QuoteCase:
    case = store.get(case_id)
    if case.status != CaseStatus.READY_FOR_REVIEW:
        raise ValueError(f"case {case_id} is {case.status.value}, not ready for review")
    target = REVIEW_OUTCOME[decision.action]
    check_transition(case.status, target)

    case.review = decision
    if decision.action == ReviewAction.APPROVE:
        case.quotation = build_quotation(case, today=today)

    now = datetime.now(UTC)
    message = f"{decision.reviewer}: {decision.action.value}" + (f" - {decision.comment}" if decision.comment else "")
    if case.quotation is not None:
        message += f" | quotation {case.quotation.quote_number} generated"
    event = CaseEvent(at=now, stage="review", message=message, from_status=case.status, to_status=target)

    case.status = target
    case.updated_at = now
    store.save(case, event)
    return store.get(case_id)

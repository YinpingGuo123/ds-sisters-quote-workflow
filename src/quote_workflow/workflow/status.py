"""The case state machine: which transitions are allowed, and nothing else.

RECEIVED ──(request incomplete)──► NEEDS_INFO ──(request completed)──► READY_FOR_REVIEW
RECEIVED ──(request complete + priced)─────────────────────────────► READY_FOR_REVIEW
RECEIVED / NEEDS_INFO / READY_FOR_REVIEW ──(unhandled error)──► FAILED ──(re-run)──► RECEIVED
READY_FOR_REVIEW ──APPROVE──► APPROVED   ──REJECT──► REJECTED   ──REQUEST_INFO──► NEEDS_INFO
"""

from __future__ import annotations

from quote_workflow.contracts.enums import CaseStatus, ReviewAction

_ALLOWED: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {CaseStatus.NEEDS_INFO, CaseStatus.READY_FOR_REVIEW, CaseStatus.FAILED},
    CaseStatus.NEEDS_INFO: {CaseStatus.NEEDS_INFO, CaseStatus.READY_FOR_REVIEW, CaseStatus.FAILED},
    CaseStatus.READY_FOR_REVIEW: {
        CaseStatus.APPROVED,
        CaseStatus.REJECTED,
        CaseStatus.NEEDS_INFO,
        CaseStatus.READY_FOR_REVIEW,  # re-priced
        CaseStatus.FAILED,
    },
    CaseStatus.FAILED: {CaseStatus.RECEIVED, CaseStatus.NEEDS_INFO, CaseStatus.READY_FOR_REVIEW},
    CaseStatus.APPROVED: set(),
    CaseStatus.REJECTED: set(),
}

REVIEW_OUTCOME: dict[ReviewAction, CaseStatus] = {
    ReviewAction.APPROVE: CaseStatus.APPROVED,
    ReviewAction.REJECT: CaseStatus.REJECTED,
    ReviewAction.REQUEST_INFO: CaseStatus.NEEDS_INFO,
}


class InvalidTransition(ValueError):
    pass


def check_transition(current: CaseStatus, target: CaseStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"cannot move a case from {current.value} to {target.value}")


def is_terminal(status: CaseStatus) -> bool:
    return not _ALLOWED[status]

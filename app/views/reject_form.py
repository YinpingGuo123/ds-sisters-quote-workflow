"""Rejecting a case: the reason is required, so it is asked for in a dialog
rather than sitting on every case as a mostly-unused control.

Reject means "no quote at all". Declining the customer's asking price is not
rejection - the engine already produced a counter, and approving the case
sends it.

Presentation only: ``workflow.apply_review`` enforces the same rule, so a
rejection can never reach a case without a reason.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import RejectionReason, ReviewAction
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.contracts.store import CaseStore
from quote_workflow.workflow import apply_review

OPEN_REJECT_CASE = "reject_dialog_case_id"

REASON_LABEL = {
    RejectionReason.PRICE: "Price - they will not pay what policy allows",
    RejectionReason.CREDIT: "Credit - customer not approved for terms",
    RejectionReason.UNAVAILABLE: "Unavailable - we cannot supply it",
    RejectionReason.CUSTOMER_WITHDREW: "Customer withdrew the request",
    RejectionReason.OTHER: "Other",
}


def _close_reject() -> None:
    st.session_state[OPEN_REJECT_CASE] = None


def request_reject(case_id: str) -> None:
    """Open the reject dialog for this case on this and following runs."""
    st.session_state[OPEN_REJECT_CASE] = case_id


def render_reject_dialog(case: QuoteCase, store: CaseStore, viewer: str) -> None:
    if st.session_state.get(OPEN_REJECT_CASE) == case.case_id:
        reject_dialog(case, store, viewer)


@st.dialog("Reject this case", on_dismiss=_close_reject)
def reject_dialog(case: QuoteCase, store: CaseStore, viewer: str) -> None:
    st.caption(
        f"{case.case_id} will be closed without a quotation. If the issue is only the price, "
        "approving sends our counter instead."
    )
    reason = st.radio(
        "Why?",
        list(REASON_LABEL),
        format_func=REASON_LABEL.__getitem__,
        key=f"{case.case_id}-reject-reason",
    )
    comment = st.text_input("Comment (optional)", key=f"{case.case_id}-reject-comment")

    if not st.button("Reject case", type="primary", key=f"{case.case_id}-reject-confirm"):
        return
    decision = ReviewDecision(
        action=ReviewAction.REJECT,
        reviewer=viewer,
        comment=comment.strip() or None,
        rejection_reason=reason,
        decided_at=datetime.now(UTC),
    )
    try:
        apply_review(store, case.case_id, decision)
    except ValueError as exc:  # decided in another tab, or no longer in review
        st.error(str(exc))
        return
    _close_reject()
    st.rerun()

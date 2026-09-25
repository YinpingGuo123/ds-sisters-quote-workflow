"""The "Ask AI to Revise" dialog: send a case back, or ask the customer.

One button in the action bar, three destinations, because the reviewer's
complaint decides who has to act:

- the summary reads badly        -> explain rework, our own stage
- the price needs recomputing    -> pricing rework, our own stage
- the customer has to answer     -> REQUEST_INFO, which is not rework at all

Presentation only: the first two call ``workflow.request_rework``, the third
``workflow.apply_review``. Neither sets a status here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import ReviewAction, ReworkTarget
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.contracts.store import CaseStore
from quote_workflow.workflow import apply_review, request_rework

OPEN_REVISE_CASE = "revise_dialog_case_id"

_ASK_CUSTOMER = "Ask the customer for more information"
_CHOICES = {
    "Reword the reviewer summary": ReworkTarget.EXPLAIN,
    "Recompute the pricing": ReworkTarget.PRICING,
    _ASK_CUSTOMER: None,
}
_HELP = {
    ReworkTarget.EXPLAIN: "Regenerates the AI summary with your reason as context. No price changes.",
    ReworkTarget.PRICING: "Re-runs the deterministic pricing engine, picking up any policy change.",
    None: "Moves the case to Needs Info. Nothing is re-run until the information arrives.",
}


def _close_revise() -> None:
    st.session_state[OPEN_REVISE_CASE] = None


def request_revise(case_id: str) -> None:
    """Open the revise dialog for this case on this and following runs."""
    st.session_state[OPEN_REVISE_CASE] = case_id


def render_revise_dialog(case: QuoteCase, store: CaseStore, viewer: str) -> None:
    if st.session_state.get(OPEN_REVISE_CASE) == case.case_id:
        revise_dialog(case, store, viewer)


@st.dialog("Ask AI to revise", on_dismiss=_close_revise)
def revise_dialog(case: QuoteCase, store: CaseStore, viewer: str) -> None:
    choice = st.radio("What needs another pass?", list(_CHOICES), key=f"{case.case_id}-revise-what")
    target = _CHOICES[choice]
    st.caption(_HELP[target])
    reason = st.text_area(
        "Why? The reviewer summary rework passes this to the AI.",
        key=f"{case.case_id}-revise-reason",
        placeholder="e.g. the summary does not mention the expired deal",
    )

    if not st.button("Send back", type="primary", key=f"{case.case_id}-revise-send"):
        return
    if not reason.strip():
        st.error("Please say why - it is recorded on the case and steers the rework.")
        return

    try:
        if target is None:
            decision = ReviewDecision(
                action=ReviewAction.REQUEST_INFO, reviewer=viewer, comment=reason.strip(), decided_at=datetime.now(UTC)
            )
            apply_review(store, case.case_id, decision)
        else:
            request_rework(store, case.case_id, target, reason.strip(), viewer)
    except ValueError as exc:  # decided in another tab, or no longer in review
        st.error(str(exc))
        return
    _close_revise()
    st.rerun()

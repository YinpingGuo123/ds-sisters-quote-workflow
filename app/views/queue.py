"""Queue views: My Queue / All Cases / Needs Attention / Completed.

Reads cases through the store and lets the user pick one; the detail view
renders below. "Needs Attention" is derived from what pricing and the
completeness rule already recorded - it is not a stored flag.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from resources import MANAGER

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import CaseStatus, PricingStatus
from quote_workflow.contracts.store import CaseStore
from ui import PRICING_LABEL, STATUS_LABEL, money, when

_COMPLETED = {CaseStatus.APPROVED, CaseStatus.REJECTED}
# Pricing outcomes a human has to weigh in on, rather than simply approve.
_ATTENTION_PRICING = {
    PricingStatus.COUNTER_RECOMMENDED,
    PricingStatus.ESCALATION_REQUIRED,
    PricingStatus.INSUFFICIENT_DATA,
}
_ATTENTION_STATUS = {CaseStatus.NEEDS_INFO, CaseStatus.FAILED}

SUBTITLE = {
    "My Queue": "Cases assigned to you for review",
    "All Cases": "Every case in the store",
    "Needs Attention": "Open cases that need something beyond a routine approval",
    "Completed": "Approved and rejected cases",
}


def needs_attention(case: QuoteCase) -> bool:
    """Waiting on information, failed, or priced into a decision a human must make."""
    if case.status in _COMPLETED:
        return False
    if case.status in _ATTENTION_STATUS:
        return True
    return bool(case.pricing and (case.pricing.status in _ATTENTION_PRICING or case.pricing.warnings))


def _cases_for(store: CaseStore, view: str, viewer: str) -> list[QuoteCase]:
    if view == "My Queue":
        return store.list() if viewer == MANAGER else store.list(assigned_to=viewer)
    if view == "Needs Attention":
        return [case for case in store.list() if needs_attention(case)]
    if view == "Completed":
        return [case for case in store.list() if case.status in _COMPLETED]
    return store.list()


def _row(case: QuoteCase) -> dict:
    return {
        "Case": case.case_id,
        "Customer": case.customer_display,
        "Status": STATUS_LABEL[case.status],
        "Pricing": PRICING_LABEL[case.pricing.status] if case.pricing else "-",
        "Total": money(case.total_quoted_value),
        "Assigned to": case.assigned_to or "-",
        "Updated": when(case.updated_at),
    }


def render_queue(store: CaseStore, view: str, viewer: str) -> str | None:
    """Render the queue table; return the selected case id (or None)."""
    cases = _cases_for(store, view, viewer)
    subtitle = "Every open case" if view == "My Queue" and viewer == MANAGER else SUBTITLE[view]

    heading, count = st.columns([4, 1])
    heading.subheader(view)
    heading.caption(subtitle)
    count.markdown(f"<div style='text-align:right'>{len(cases)} case(s)</div>", unsafe_allow_html=True)
    if not cases:
        st.info("No cases here.")
        return None

    frame = pd.DataFrame([_row(case) for case in cases])
    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"queue-{view}",
    )
    rows = event.selection.rows if event and event.selection else []
    if rows:
        return cases[rows[0]].case_id
    return cases[0].case_id if len(cases) == 1 else None

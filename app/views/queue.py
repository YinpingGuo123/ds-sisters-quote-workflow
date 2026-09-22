"""Queue views: My Queue / All Cases / Needs Info / Completed.

Reads the store's list (denormalised columns, no events) and lets the user
pick a case; the detail view renders below.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.contracts.store import CaseStore
from ui import PRICING_LABEL, STATUS_LABEL, money, when

VIEWS = ["My Queue", "All Cases", "Needs Info", "Completed"]
_COMPLETED = {CaseStatus.APPROVED, CaseStatus.REJECTED}
_MANAGER = "Manager (all cases)"


def _cases_for(store: CaseStore, view: str, viewer: str) -> list[QuoteCase]:
    if view == "My Queue":
        cases = store.list() if viewer == _MANAGER else store.list(assigned_to=viewer)
        return [c for c in cases if c.status not in _COMPLETED]
    if view == "Needs Info":
        return store.list(status=CaseStatus.NEEDS_INFO)
    if view == "Completed":
        return [c for c in store.list() if c.status in _COMPLETED]
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
    subtitle = {
        "My Queue": f"Cases assigned to {viewer}" if viewer != _MANAGER else "Every open case",
        "All Cases": "Every case in the store",
        "Needs Info": "Cases waiting for missing information",
        "Completed": "Approved and rejected cases",
    }[view]
    st.subheader(view)
    st.caption(f"{subtitle} - {len(cases)} case(s)")
    if not cases:
        st.info("No cases here.")
        return None

    frame = pd.DataFrame([_row(c) for c in cases])
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

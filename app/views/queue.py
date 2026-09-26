"""Queue views: My Queue / All Cases / Needs Attention / Completed.

Reads cases through the store and lets the user pick one; the detail view
renders below. "Needs Attention" is derived from what pricing and the
completeness rule already recorded - it is not a stored flag.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
_ATTENTION_STATUS = {CaseStatus.NEEDS_INFO, CaseStatus.FAILED, CaseStatus.REWORK_REQUESTED}

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


_ANY = "Any"
_WINDOWS = {"Any time": None, "Today": 1, "Last 7 days": 7, "Last 30 days": 30}


def _matches_search(case: QuoteCase, needle: str) -> bool:
    """Case id, customer and product names - what a reviewer would type."""
    haystack = [case.case_id, case.customer_display, case.assigned_to or ""]
    if case.request:
        haystack += [line.product_name or "" for line in case.request.lines]
    return any(needle in field.lower() for field in haystack)


def _filters(cases: list[QuoteCase], view: str) -> list[QuoteCase]:
    """Narrow the queue. Pure presentation - the store is never re-queried."""
    search = st.text_input(
        "Search",
        key=f"search-{view}",
        placeholder="Search quotes, customers, or products...",
        label_visibility="collapsed",
    )
    cols = st.columns(4)
    statuses = sorted({STATUS_LABEL[case.status] for case in cases})
    status = cols[0].selectbox("Status", [_ANY, *statuses], key=f"f-status-{view}")
    owners = sorted({case.assigned_to or "-" for case in cases})
    owner = cols[1].selectbox("Assigned to", [_ANY, *owners], key=f"f-owner-{view}")
    customers = sorted({case.customer_display for case in cases})
    customer = cols[2].selectbox("Customer", [_ANY, *customers], key=f"f-customer-{view}")
    window = cols[3].selectbox("Updated", list(_WINDOWS), key=f"f-window-{view}")

    if status != _ANY:
        cases = [case for case in cases if STATUS_LABEL[case.status] == status]
    if owner != _ANY:
        cases = [case for case in cases if (case.assigned_to or "-") == owner]
    if customer != _ANY:
        cases = [case for case in cases if case.customer_display == customer]
    if days := _WINDOWS[window]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cases = [case for case in cases if case.updated_at >= cutoff]
    if needle := search.strip().lower():
        cases = [case for case in cases if _matches_search(case, needle)]
    return cases


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
    everything = _cases_for(store, view, viewer)
    subtitle = "Every open case" if view == "My Queue" and viewer == MANAGER else SUBTITLE[view]

    heading, count = st.columns([4, 1])
    heading.subheader(view)
    heading.caption(subtitle)
    if not everything:
        count.markdown("<div style='text-align:right'>0 cases</div>", unsafe_allow_html=True)
        st.info("No cases here.")
        return None

    cases = _filters(everything, view)
    shown = f"{len(cases)} of {len(everything)}" if len(cases) != len(everything) else f"{len(cases)}"
    count.markdown(f"<div style='text-align:right'>{shown} case(s)</div>", unsafe_allow_html=True)
    if not cases:
        st.info("No case matches these filters.")
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

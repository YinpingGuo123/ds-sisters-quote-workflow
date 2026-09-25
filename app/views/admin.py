"""Admin / Monitoring: is the store healthy and what is this build running?

Everything here is read from data the system already produces - case rows,
case_events, the policy file and the catalog. Nothing is computed for this
page alone, and it changes no state.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st
from resources import catalog, store

from quote_workflow.catalog.repository import table_counts
from quote_workflow.config import openai_model
from quote_workflow.contracts.case import SCHEMA_VERSION
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.pricing.policy import load_policy
from ui import STATUS_LABEL, money, when


def _case_health() -> None:
    cases = store().list()
    st.subheader("Cases")
    st.caption(f"{len(cases)} case(s) in the store")
    if not cases:
        st.info("The store is empty.")
        return

    counts = Counter(case.status for case in cases)
    rows = [
        {"Status": STATUS_LABEL[status], "Cases": counts.get(status, 0)}
        for status in CaseStatus
        if counts.get(status, 0)
    ]
    table, chart = st.columns([1, 2])
    table.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    chart.bar_chart(pd.DataFrame(rows).set_index("Status"), horizontal=True)

    quoted = [case.total_quoted_value for case in cases if case.total_quoted_value is not None]
    cols = st.columns(3)
    cols[0].metric("Priced cases", len(quoted))
    cols[1].metric("Quoted value", money(sum(quoted)) if quoted else "-")
    cols[2].metric("Awaiting rework", counts.get(CaseStatus.REWORK_REQUESTED, 0))


def _failures() -> None:
    st.subheader("Failures")
    failed = store().list(status=CaseStatus.FAILED)
    if not failed:
        st.success("No case is in a failed state.")
        return
    for case in failed:
        with st.container(border=True):
            st.markdown(f"**{case.case_id}** · {case.customer_display} · updated {when(case.updated_at)}")
            for event in case.events:
                if event.level == "error":
                    st.error(f"[{event.stage}] {event.message}")


def _build_info() -> None:
    st.subheader("Build")
    policy = load_policy()
    cols = st.columns(4)
    cols[0].metric("Case schema", SCHEMA_VERSION)
    cols[1].metric("Pricing policy", policy.version)
    cols[2].metric("Reviewer summary", "LLM" if st.session_state.get("use_llm") else "fallback")
    cols[3].metric("Model", openai_model())
    st.caption(
        "Pricing is deterministic in every configuration. The reviewer-summary setting only "
        "affects wording, never a price or a status."
    )


def _catalog_info() -> None:
    st.subheader("Reference catalog")
    counts = table_counts(catalog())
    st.dataframe(
        pd.DataFrame([{"Table": name, "Records": count} for name, count in counts.items()]),
        hide_index=True,
        width="stretch",
    )
    if not counts.get("products") or not counts.get("customers"):
        st.warning("The catalog looks empty - run `python scripts/build_db.py`.")


def render_admin() -> None:
    st.subheader("Admin / Monitoring")
    st.caption("Store health and what this build is running. Read-only.")
    _case_health()
    _failures()
    _build_info()
    _catalog_info()

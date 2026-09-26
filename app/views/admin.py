"""Admin / Monitoring: is the store healthy and what is this build running?

Everything here is read from data the system already produces - case rows,
case_events, the policy file and the catalog. Nothing is computed for this
page alone, and it changes no state.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st
from resources import catalog, store, use_llm

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


def _rejections() -> None:
    """Why quotes were not sent - the question the free-text comment could not answer."""
    st.subheader("Rejections")
    rejected = store().list(status=CaseStatus.REJECTED)
    if not rejected:
        st.caption("No rejected cases.")
        return
    counts = Counter(
        case.review.rejection_reason.value.replace("_", " ") if case.review and case.review.rejection_reason else "-"
        for case in rejected
    )
    rows = [{"Reason": reason, "Cases": count} for reason, count in counts.most_common()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if counts.get("-"):
        st.caption(f"{counts['-']} rejected before a reason was recorded.")


def _build_info() -> None:
    st.subheader("Build")
    policy = load_policy()
    # Count what actually happened rather than whether a key is set. summarize()
    # degrades to the fallback on any failure, so a misconfigured client produces a
    # plausible summary and no error - "key present" would report LLM either way.
    written_by = Counter(case.summary.generated_by for case in store().list() if case.summary)
    by_llm, by_fallback = written_by.get("llm", 0), written_by.get("fallback", 0)

    cols = st.columns(4)
    cols[0].metric("Case schema", SCHEMA_VERSION)
    cols[1].metric("Pricing policy", policy.version)
    cols[2].metric("Summaries by LLM", f"{by_llm} of {by_llm + by_fallback}")
    cols[3].metric("Model", openai_model() if use_llm() else "not configured")

    if use_llm() and by_llm == 0 and by_fallback:
        st.warning(
            "An API key is configured, but every reviewer summary so far was written by the "
            "deterministic fallback. Open a case and check the AI Reviewer Summary card for the "
            "rejection reason - the LLM path fails quietly by design."
        )
    st.caption(
        "Pricing is deterministic in every configuration; the reviewer summary only affects "
        "wording, never a price or a status. Whether the LLM is used follows OPENAI_API_KEY - "
        "it is not a per-review choice."
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
    _rejections()
    _failures()
    _build_info()
    _catalog_info()

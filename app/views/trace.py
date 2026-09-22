"""Technical Trace: the case's event history, stage timings, and the raw case
record. Reads ``case_events`` through the store; nothing here is business logic."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quote_workflow.contracts.case import QuoteCase
from ui import when


def render_trace(case: QuoteCase) -> None:
    st.markdown("#### Event history")
    if not case.events:
        st.info("No events recorded.")
    else:
        rows = []
        previous = case.events[0].at
        for event in case.events:
            rows.append(
                {
                    "At": when(event.at),
                    "+ms": int((event.at - previous).total_seconds() * 1000),
                    "Stage": event.stage,
                    "Level": event.level,
                    "Transition": f"{event.from_status.value} -> {event.to_status.value}" if event.to_status else "",
                    "Message": event.message,
                }
            )
            previous = event.at
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    cols = st.columns(3)
    cols[0].metric("Schema version", case.schema_version)
    cols[1].metric("Policy version", case.pricing.policy_version if case.pricing else "-")
    cols[2].metric("Summary source", case.summary.generated_by if case.summary else "-")
    if case.trace_id:
        st.caption(f"Trace id: `{case.trace_id}`")

    with st.expander("Raw case record (JSON)"):
        st.json(case.model_dump(mode="json"))

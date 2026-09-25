"""Processing Timeline: what has happened to this case, from ``case_events``.

Every row is a persisted event. The labels are friendlier than the raw stage
names, but nothing here is invented - a step appears because it was recorded.
"""

from __future__ import annotations

import streamlit as st

from quote_workflow.contracts.case import CaseEvent, QuoteCase
from ui import STATUS_LABEL

# Used when an event records no status change, so the stage is all we have.
_STAGE_LABEL = {
    "intake": "Intake",
    "pricing": "Priced",
    "explain": "AI summary",
    "review": "Reviewer",
    "pipeline": "Pipeline",
}

_ICON = {"info": ":material/check_circle:", "warning": ":material/warning:", "error": ":material/error:"}


def _label(event: CaseEvent) -> str:
    if event.to_status is not None:
        return STATUS_LABEL[event.to_status]
    return _STAGE_LABEL.get(event.stage, event.stage.title())


def render_timeline(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/schedule: Processing Timeline")
        if not case.events:
            st.caption("No events recorded.")
            return
        last = len(case.events) - 1
        for index, event in enumerate(case.events):
            icon = ":material/radio_button_checked:" if index == last else _ICON[event.level]
            st.markdown(f"{icon} **{_label(event)}**")
            st.caption(f"{event.at.astimezone():%b %d, %H:%M} · {event.message}")

"""Processing Timeline: the milestones of a case, from ``case_events``.

Milestones only - every status change, plus each time the case was priced,
because the total is what a reviewer is looking for. Everything else (the
summary call, "request complete", rework bookkeeping) is real history but
noise in a narrow rail, and lives in the Technical Trace tab instead.

Without that filter the rail grows by four rows per rework round and stops
being readable after two or three. Nothing here is invented: a milestone
appears because it was recorded.
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


def _is_milestone(event: CaseEvent) -> bool:
    """A status change, or a pricing run. See the module docstring."""
    return event.to_status is not None or event.stage == "pricing"


def render_timeline(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/schedule: Processing Timeline")
        if not case.events:
            st.caption("No events recorded.")
            return

        milestones = [event for event in case.events if _is_milestone(event)]
        last = case.events[-1]
        for event in milestones:
            icon = ":material/radio_button_checked:" if event is last else _ICON[event.level]
            st.markdown(f"{icon} **{_label(event)}**")
            st.caption(f"{event.at.astimezone():%b %d, %H:%M} · {event.message}")

        hidden = len(case.events) - len(milestones)
        if hidden:
            st.caption(f"+ {hidden} more step(s) - see the Technical Trace tab.")

"""One screen of the portal: a queue on top, the selected case below.

Every navigation item renders the same body with a different queue, which is
why the screens under ``app/screens/`` are one line each. The selected case is
kept in session state so it survives switching queues.
"""

from __future__ import annotations

import streamlit as st
from resources import catalog, store, viewer

from views.case_detail import render_case
from views.queue import render_queue
from views.trace import render_trace

SELECTED = "selected_case"


def render_workspace(view: str) -> None:
    case_store, conn, who = store(), catalog(), viewer()

    selected = render_queue(case_store, view, who)
    if selected:
        st.session_state[SELECTED] = selected

    case_id = st.session_state.get(SELECTED)
    if not case_id:
        st.caption("Select a case in the table to open it.")
        return
    try:
        case = case_store.get(case_id)
    except KeyError:  # the case was removed, or the store was reseeded
        st.session_state.pop(SELECTED, None)
        return

    st.divider()
    business, trace = st.tabs(["Business View", "Technical Trace"])
    with business:
        render_case(case, case_store, conn, who)
    with trace:
        render_trace(case)

"""Quote Review Portal - Streamlit entry point.

Presentation only: reads cases through the CaseStore, calls ``workflow``
for every action. Never prices, resolves, or calls an LLM directly.
"""

from __future__ import annotations

import hmac
import os

import streamlit as st


def _load_secrets_into_env() -> None:
    """Expose Streamlit secrets (Cloud secrets panel / .streamlit/secrets.toml)
    as environment variables, so ``config.py`` sees one set of names. Must run
    before any quote_workflow import that reads the environment."""
    try:
        st.secrets.load_if_toml_exists()
    except Exception:  # a malformed secrets file must not take the page down
        pass


_load_secrets_into_env()

from quote_workflow.catalog.build import ensure_database  # noqa: E402
from quote_workflow.catalog.connection import get_connection  # noqa: E402
from quote_workflow.config import default_reviewer  # noqa: E402
from quote_workflow.samples import load_samples, sample_request  # noqa: E402
from quote_workflow.storage.sqlite_store import SqliteCaseStore  # noqa: E402
from quote_workflow.workflow import create_case_from_request  # noqa: E402
from views.case_detail import render_case  # noqa: E402
from views.queue import VIEWS, render_queue  # noqa: E402
from views.trace import render_trace  # noqa: E402

st.set_page_config(page_title="Quote Review Portal", page_icon=":material/request_quote:", layout="wide")


def _require_access_code() -> None:
    """Optional passphrase gate for a public deployment (``ACCESS_CODE``). Off when unset."""
    try:
        expected = st.secrets.get("ACCESS_CODE")
    except Exception:
        expected = None
    expected = expected or os.environ.get("ACCESS_CODE")
    if not expected or st.session_state.get("access_granted"):
        return
    st.title("Quote Review Portal")
    code = st.text_input("Access code", type="password")
    if code:
        if hmac.compare_digest(code.strip(), expected.strip()):
            st.session_state["access_granted"] = True
            st.rerun()
        st.error("That code is not recognized.")
    st.stop()


_require_access_code()


@st.cache_resource
def _catalog():
    ensure_database()
    return get_connection()


@st.cache_resource
def _store() -> SqliteCaseStore:
    store = SqliteCaseStore()
    if store.count() == 0:
        # Fresh checkout / new Cloud container: seed the demo cases so the queue isn't empty.
        conn = _catalog()
        for sample in load_samples():
            create_case_from_request(
                store, conn, sample_request(sample, conn), case_id=f"Q-{sample['id']}", use_llm=False
            )
    return store


conn = _catalog()
store = _store()

# --- sidebar -------------------------------------------------------------------

with st.sidebar:
    st.title("Quote Review Portal")
    reviewers = sorted({c.assigned_to for c in store.list() if c.assigned_to} | {default_reviewer()})
    viewer = st.selectbox("View as", [*reviewers, "Manager (all cases)"], index=0)
    view = st.radio("Queue", VIEWS, index=0)
    st.divider()
    st.session_state["use_llm"] = st.toggle(
        "Use LLM for reviewer summary on re-runs",
        value=bool(os.environ.get("OPENAI_API_KEY")),
        help="Pricing is always deterministic. This only affects the AI reviewer summary.",
    )
    st.caption(f"{store.count()} cases in store")

# --- main ----------------------------------------------------------------------

selected = render_queue(store, view, viewer)
if "selected_case" not in st.session_state or selected:
    st.session_state["selected_case"] = selected or st.session_state.get("selected_case")

case_id = st.session_state.get("selected_case")
if not case_id:
    st.caption("Select a case in the table to open it.")
    st.stop()

try:
    case = store.get(case_id)
except KeyError:
    st.stop()

st.divider()
business, trace = st.tabs(["Business View", "Technical Trace"])
with business:
    render_case(case, store, conn, viewer)
with trace:
    render_trace(case)

"""Quote Review Portal - Streamlit entry point.

Owns the chrome only: the optional access gate, the left navigation, and the
"view as" / LLM controls in the sidebar. Each navigation item is a screen under
``screens/`` that renders the shared workspace; nothing here reads or writes a
case.
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

from resources import MANAGER, reviewers, store  # noqa: E402

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

navigation = st.navigation(
    [
        st.Page("screens/my_queue.py", title="My Queue", icon=":material/inbox:", default=True),
        st.Page("screens/all_cases.py", title="All Cases", icon=":material/description:"),
        st.Page("screens/needs_attention.py", title="Needs Attention", icon=":material/warning:"),
        st.Page("screens/completed.py", title="Completed", icon=":material/check_circle:"),
    ]
)

# --- sidebar -------------------------------------------------------------------

with st.sidebar:
    st.divider()
    options = [*reviewers(), MANAGER]
    chosen = st.segmented_control("View as", options, default=options[0], key="view_as")
    st.session_state["viewer"] = chosen or options[0]
    st.session_state["use_llm"] = st.toggle(
        "Use LLM for reviewer summary on re-runs",
        value=bool(os.environ.get("OPENAI_API_KEY")),
        help="Pricing is always deterministic. This only affects the AI reviewer summary.",
    )
    st.caption(f"{store().count()} cases in store")

navigation.run()

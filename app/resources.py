"""Shared, cached handles for the portal.

Each navigation screen runs as its own script, so the catalog connection, the
case store and the current "view as" reviewer cannot be passed down as
arguments - they are read from here. ``st.cache_resource`` means one
connection and one store per app process, not per rerun.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

from quote_workflow.catalog.build import ensure_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.config import default_reviewer
from quote_workflow.samples import load_samples, sample_request
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import create_case_from_request

MANAGER = "Manager (all cases)"


@st.cache_resource
def catalog() -> sqlite3.Connection:
    ensure_database()
    return get_connection()


@st.cache_resource
def store() -> SqliteCaseStore:
    case_store = SqliteCaseStore()
    if case_store.count() == 0:
        # Fresh checkout / new Cloud container: seed the demo cases so the queue isn't empty.
        conn = catalog()
        for sample in load_samples():
            create_case_from_request(
                case_store, conn, sample_request(sample, conn), case_id=f"Q-{sample['id']}", use_llm=False
            )
    return case_store


def viewer() -> str:
    """Who the portal is being viewed as; set by the sidebar control."""
    return st.session_state.get("viewer") or default_reviewer()


def reviewers() -> list[str]:
    return sorted({case.assigned_to for case in store().list() if case.assigned_to} | {default_reviewer()})

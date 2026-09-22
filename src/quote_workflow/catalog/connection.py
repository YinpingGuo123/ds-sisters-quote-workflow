"""The one connection helper for the reference-data (catalog) database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from quote_workflow import config


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with dict-like rows and foreign keys enforced.

    SQLite requires ``PRAGMA foreign_keys = ON`` per-connection (it is not
    part of the persisted database state), so every caller gets it here
    rather than having to remember to set it themselves.

    ``check_same_thread=False``: callers that cache a single connection
    across calls (e.g. Streamlit's ``st.cache_resource``, whose rerun model
    doesn't guarantee the same worker thread every time) would otherwise hit
    "SQLite objects created in a thread can only be used in that same
    thread." The catalog is only ever SELECTed at runtime, so relaxing this
    check is safe - there's no concurrent-write hazard to guard against.
    """
    db_path = db_path or config.CATALOG_DB_PATH  # read at call time so tests can redirect it
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

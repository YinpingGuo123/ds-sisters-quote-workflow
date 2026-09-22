from __future__ import annotations

from pathlib import Path

import pytest

from quote_workflow.catalog.build import build_database
from quote_workflow.catalog.connection import get_connection


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """A catalog DB path under pytest's tmp_path - never touches the real dev DB."""
    return tmp_path / "catalog.db"


@pytest.fixture
def built_db(tmp_db_path: Path):
    """Build the catalog into tmp_db_path and yield an open connection."""
    build_database(db_path=tmp_db_path)
    conn = get_connection(db_path=tmp_db_path)
    try:
        yield conn
    finally:
        conn.close()

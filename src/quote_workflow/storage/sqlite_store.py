"""SQLite implementation of ``contracts.CaseStore``.

The whole QuoteCase is stored as one JSON document per row plus a few
denormalised columns for listing; events go to their own append-only table.
The store owns its schema (created on open) and its own database file,
separate from the catalog, so ``scripts/build_db.py`` never touches cases.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from quote_workflow import config
from quote_workflow.contracts.case import CaseEvent, QuoteCase
from quote_workflow.contracts.enums import CaseStatus

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class SqliteCaseStore:
    def __init__(self, db_path: Path | None = None):
        db_path = db_path or config.CASES_DB_PATH  # read at call time so tests can redirect it
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: Streamlit may call from different threads
        # across reruns; all writes are short transactions on one connection.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def close(self) -> None:
        self._conn.close()

    # --- CaseStore ---------------------------------------------------------

    def create(self, case: QuoteCase, event: CaseEvent) -> QuoteCase:
        with self._conn:
            self._conn.execute(
                "INSERT INTO cases (case_id, status, assigned_to, customer_name, total_quoted_value, "
                "created_at, updated_at, schema_version, case_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._row_values(case),
            )
            self._append_event(case.case_id, event)
        return self.get(case.case_id)

    def get(self, case_id: str) -> QuoteCase:
        row = self._conn.execute("SELECT case_json FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        case = QuoteCase.model_validate_json(row["case_json"])
        case.events = self.events(case_id)
        return case

    def save(self, case: QuoteCase, event: CaseEvent | None = None) -> None:
        with self._conn:
            values = self._row_values(case)
            cursor = self._conn.execute(
                "UPDATE cases SET status = ?, assigned_to = ?, customer_name = ?, total_quoted_value = ?, "
                "created_at = ?, updated_at = ?, schema_version = ?, case_json = ? WHERE case_id = ?",
                (*values[1:], case.case_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(case.case_id)
            if event is not None:
                self._append_event(case.case_id, event)

    def list(self, status: CaseStatus | None = None, assigned_to: str | None = None) -> list[QuoteCase]:
        clauses, params = [], []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if assigned_to is not None:
            clauses.append("assigned_to = ?")
            params.append(assigned_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(f"SELECT case_json FROM cases {where} ORDER BY updated_at DESC, case_id DESC", params)
        return [QuoteCase.model_validate_json(row["case_json"]) for row in rows]

    def events(self, case_id: str) -> list[CaseEvent]:
        rows = self._conn.execute(
            "SELECT at, stage, level, from_status, to_status, message FROM case_events "
            "WHERE case_id = ? ORDER BY event_id",
            (case_id,),
        )
        return [CaseEvent(**dict(row)) for row in rows]

    # --- helpers -----------------------------------------------------------

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]

    def _append_event(self, case_id: str, event: CaseEvent) -> None:
        self._conn.execute(
            "INSERT INTO case_events (case_id, at, stage, level, from_status, to_status, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                event.at.isoformat(),
                event.stage,
                event.level,
                event.from_status.value if event.from_status else None,
                event.to_status.value if event.to_status else None,
                event.message,
            ),
        )

    @staticmethod
    def _row_values(case: QuoteCase) -> tuple:
        return (
            case.case_id,
            case.status.value,
            case.assigned_to,
            case.customer_display if case.request or case.source else None,
            case.total_quoted_value,
            case.created_at.isoformat(),
            case.updated_at.isoformat(),
            case.schema_version,
            case.model_dump_json(),  # `events` is excluded from the dump by the model
        )

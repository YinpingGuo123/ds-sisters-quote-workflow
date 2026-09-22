"""Build the SQLite database from the hand-curated CSVs under data/reference/.

Idempotency approach: drop-and-recreate, not migrations. This is the simplest
correct option for an MVP - re-running ``build_database()`` always produces an
identical fresh database from the CSVs, which is both simple and directly
testable (see tests/catalog/test_build.py).
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from quote_workflow import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _empty_to_none(value: str) -> str | None:
    return value if value not in (None, "") else None


def _opt_int(value: str) -> int | None:
    value = _empty_to_none(value)
    return int(value) if value is not None else None


def _opt_float(value: str) -> float | None:
    value = _empty_to_none(value)
    return float(value) if value is not None else None


def _load_customers(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    records = [
        (
            int(row["customer_id"]),
            row["customer_name"],
            row["customer_category"],
            _empty_to_none(row["buying_group"]),
            float(row["credit_limit"]),
            row["customer_tier"],
        )
        for row in rows
    ]
    conn.executemany(
        "INSERT INTO customers "
        "(customer_id, customer_name, customer_category, buying_group, credit_limit, customer_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        records,
    )
    return len(records)


def _load_products(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    records = [
        (
            int(row["product_id"]),
            row["product_name"],
            float(row["list_price"]),
            float(row["cost_price"]),
            row["product_category"],
        )
        for row in rows
    ]
    conn.executemany(
        "INSERT INTO products (product_id, product_name, list_price, cost_price, product_category) "
        "VALUES (?, ?, ?, ?, ?)",
        records,
    )
    return len(records)


def _load_aliases(conn: sqlite3.Connection, table: str, id_column: str, rows: list[dict[str, str]]) -> int:
    records = [(row["alias"].strip(), int(row[id_column])) for row in rows]
    conn.executemany(f"INSERT INTO {table} (alias, {id_column}) VALUES (?, ?)", records)
    return len(records)


def _load_sales_history(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    records = [
        (
            int(row["sale_id"]),
            int(row["customer_id"]),
            int(row["product_id"]),
            row["sale_date"],
            int(row["quantity"]),
            float(row["unit_price"]),
        )
        for row in rows
    ]
    conn.executemany(
        "INSERT INTO sales_history "
        "(sale_id, customer_id, product_id, sale_date, quantity, unit_price) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        records,
    )
    return len(records)


def _load_special_deals(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    records = [
        (
            int(row["deal_id"]),
            _opt_int(row["customer_id"]),
            _empty_to_none(row["buying_group"]),
            _empty_to_none(row["customer_category"]),
            _opt_int(row["product_id"]),
            _opt_int(row["min_quantity"]),
            row["start_date"],
            row["end_date"],
            _opt_float(row["discount_pct"]),
            _opt_float(row["fixed_unit_price"]),
        )
        for row in rows
    ]
    conn.executemany(
        "INSERT INTO special_deals "
        "(deal_id, customer_id, buying_group, customer_category, product_id, "
        "min_quantity, start_date, end_date, discount_pct, fixed_unit_price) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        records,
    )
    return len(records)


def build_database(db_path: Path | None = None, raw_dir: Path | None = None) -> dict[str, int]:
    """Rebuild the SQLite database from scratch and return per-table row counts."""
    db_path = db_path or config.CATALOG_DB_PATH
    raw_dir = raw_dir or config.REFERENCE_DIR
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        counts = {
            "customers": _load_customers(conn, _read_csv(raw_dir / "customers.csv")),
            "products": _load_products(conn, _read_csv(raw_dir / "products.csv")),
            "sales_history": _load_sales_history(conn, _read_csv(raw_dir / "sales_history.csv")),
            "special_deals": _load_special_deals(conn, _read_csv(raw_dir / "special_deals.csv")),
            "customer_aliases": _load_aliases(
                conn, "customer_aliases", "customer_id", _read_csv(raw_dir / "customer_aliases.csv")
            ),
            "product_aliases": _load_aliases(
                conn, "product_aliases", "product_id", _read_csv(raw_dir / "product_aliases.csv")
            ),
        }
        conn.commit()
    finally:
        conn.close()

    return counts


def ensure_database(db_path: Path | None = None, raw_dir: Path | None = None) -> bool:
    """Build the database only if the file doesn't exist yet. Returns True if it built.

    The generated ``.db`` is git-ignored, so on a fresh checkout (or a Streamlit
    Community Cloud container) it simply isn't there. The Streamlit app calls
    this on startup so a first visitor doesn't hit "no such table"; local
    developers can still force a rebuild with ``scripts/build_db.py``.
    """
    db_path = db_path or config.CATALOG_DB_PATH
    if db_path.exists():
        return False
    build_database(db_path=db_path, raw_dir=raw_dir)
    return True

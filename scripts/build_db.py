"""Rebuild data/db/catalog.db from data/reference/*.csv. Never touches cases.db.

Usage:
    python scripts/build_db.py
"""

from __future__ import annotations

from quote_workflow.catalog.build import build_database
from quote_workflow.config import CATALOG_DB_PATH


def main() -> None:
    counts = build_database()
    print(f"Built {CATALOG_DB_PATH}")
    for table, count in counts.items():
        print(f"  {table}: {count} rows")


if __name__ == "__main__":
    main()

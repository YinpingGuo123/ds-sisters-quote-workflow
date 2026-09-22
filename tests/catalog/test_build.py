from __future__ import annotations

import csv
import sqlite3
from datetime import date
from pathlib import Path

from quote_workflow import config
from quote_workflow.catalog.build import build_database, ensure_database

TABLES = ["customers", "products", "sales_history", "special_deals", "customer_aliases", "product_aliases"]


def _csv_row_count(name: str) -> int:
    with (config.REFERENCE_DIR / name).open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def test_all_tables_exist(built_db: sqlite3.Connection):
    existing = {row["name"] for row in built_db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in TABLES:
        assert table in existing


def test_row_counts_match_source_csvs(built_db: sqlite3.Connection):
    expected = {
        "customers": _csv_row_count("customers.csv"),
        "products": _csv_row_count("products.csv"),
        "sales_history": _csv_row_count("sales_history.csv"),
        "special_deals": _csv_row_count("special_deals.csv"),
        "customer_aliases": _csv_row_count("customer_aliases.csv"),
        "product_aliases": _csv_row_count("product_aliases.csv"),
    }
    for table, expected_count in expected.items():
        actual = built_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert actual == expected_count, f"{table}: expected {expected_count}, got {actual}"


def test_foreign_keys_are_clean(built_db: sqlite3.Connection):
    violations = built_db.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_special_deals_always_have_a_price_rule(built_db: sqlite3.Connection):
    rows = built_db.execute("SELECT deal_id, discount_pct, fixed_unit_price FROM special_deals").fetchall()
    for row in rows:
        assert row["discount_pct"] is not None or row["fixed_unit_price"] is not None, (
            f"deal_id {row['deal_id']} has neither discount_pct nor fixed_unit_price"
        )


def test_customer_names_are_unique_and_not_null(built_db: sqlite3.Connection):
    names = [row["customer_name"] for row in built_db.execute("SELECT customer_name FROM customers")]
    assert all(name for name in names)
    assert len(names) == len(set(names))


def test_product_names_are_unique_and_not_null(built_db: sqlite3.Connection):
    names = [row["product_name"] for row in built_db.execute("SELECT product_name FROM products")]
    assert all(name for name in names)
    assert len(names) == len(set(names))


def test_every_customer_has_a_valid_tier(built_db: sqlite3.Connection):
    tiers = {row["customer_tier"] for row in built_db.execute("SELECT customer_tier FROM customers")}
    assert tiers <= {"standard", "preferred", "strategic"}
    # The segment guardrails only mean something if more than one tier exists.
    assert len(tiers) >= 2


def test_every_product_has_a_category(built_db: sqlite3.Connection):
    categories = [row["product_category"] for row in built_db.execute("SELECT product_category FROM products")]
    assert all(categories)
    # At least one category with 2+ products, so "the mugs" is a real ambiguity scenario.
    assert max(categories.count(c) for c in set(categories)) >= 2


def test_aliases_resolve_case_insensitively(built_db: sqlite3.Connection):
    row = built_db.execute("SELECT customer_id FROM customer_aliases WHERE alias = ?", ("wt retail",)).fetchone()
    assert row is not None and row["customer_id"] == 5
    row = built_db.execute("SELECT product_id FROM product_aliases WHERE alias = ?", ("LAUNCHERS",)).fetchone()
    assert row is not None and row["product_id"] == 1


def test_aliases_never_shadow_a_real_name(built_db: sqlite3.Connection):
    """An alias equal to an actual customer/product name would be redundant at
    best and, if it pointed elsewhere, would silently override exact matching."""
    clashes = built_db.execute(
        "SELECT a.alias FROM customer_aliases a JOIN customers c ON lower(a.alias) = lower(c.customer_name)"
    ).fetchall()
    assert clashes == []
    clashes = built_db.execute(
        "SELECT a.alias FROM product_aliases a JOIN products p ON lower(a.alias) = lower(p.product_name)"
    ).fetchall()
    assert clashes == []


def test_rebuild_is_idempotent(tmp_db_path: Path):
    first = build_database(db_path=tmp_db_path)
    second = build_database(db_path=tmp_db_path)
    assert first == second


def test_ensure_database_builds_only_when_missing(tmp_db_path: Path):
    assert not tmp_db_path.exists()
    assert ensure_database(db_path=tmp_db_path) is True
    assert tmp_db_path.exists()

    # Second call must be a no-op: same file, untouched, nothing rebuilt.
    mtime_before = tmp_db_path.stat().st_mtime_ns
    assert ensure_database(db_path=tmp_db_path) is False
    assert tmp_db_path.stat().st_mtime_ns == mtime_before


def test_deal_scenario_coverage(built_db: sqlite3.Connection):
    """Pins the hand-authored special_deals scenario matrix so later edits to
    the CSV can't silently drop a scenario the eval milestone will rely on.
    """

    def count(where: str) -> int:
        return built_db.execute(f"SELECT COUNT(*) FROM special_deals WHERE {where}").fetchone()[0]

    assert count("customer_id IS NOT NULL") >= 1, "no customer-specific deal"
    assert count("buying_group IS NOT NULL") >= 1, "no buying-group deal"
    assert count("customer_category IS NOT NULL") >= 1, "no category deal"
    assert count("min_quantity IS NOT NULL") >= 1, "no quantity-threshold deal"
    assert count("fixed_unit_price IS NOT NULL") >= 1, "no fixed-price deal"
    assert count("discount_pct IS NOT NULL") >= 1, "no percentage-discount deal"
    # Deliberately NO always-on category deal with product_id NULL: it would
    # shadow the standard volume/term ladders for a whole category. The
    # engine's wildcard handling is covered in tests/test_pricing_engine.py.
    assert count("customer_category IS NOT NULL AND product_id IS NULL") == 0

    today = date.today().isoformat()
    assert count(f"end_date < '{today}'") >= 1, "no expired deal"


def test_no_history_customers_and_products_exist(built_db: sqlite3.Connection):
    """At least one customer and one product must have zero sales_history rows,
    so later milestones have a real 'no historical reference' scenario to test.
    """
    no_history_customers = built_db.execute(
        "SELECT COUNT(*) FROM customers c "
        "WHERE NOT EXISTS (SELECT 1 FROM sales_history s WHERE s.customer_id = c.customer_id)"
    ).fetchone()[0]
    no_history_products = built_db.execute(
        "SELECT COUNT(*) FROM products p "
        "WHERE NOT EXISTS (SELECT 1 FROM sales_history s WHERE s.product_id = p.product_id)"
    ).fetchone()[0]
    assert no_history_customers >= 1
    assert no_history_products >= 1

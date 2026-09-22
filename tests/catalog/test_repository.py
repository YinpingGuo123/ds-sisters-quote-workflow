from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from quote_workflow.catalog.repository import (
    find_customer,
    find_product,
    get_customer,
    get_customer_by_id,
    get_deals,
    get_product,
    get_product_by_id,
    get_sales_history,
    search_customers,
    search_products,
)

AS_OF = date(2026, 9, 5)


# --- get_customer / get_product ---------------------------------------------


def test_get_customer_exact_match(built_db: sqlite3.Connection):
    customer = get_customer(built_db, "Tailspin Toys (Head Office)")
    assert customer is not None
    assert customer.customer_id == 1
    assert customer.buying_group == "Tailspin Toys"


def test_get_customer_carries_tier(built_db: sqlite3.Connection):
    assert get_customer(built_db, "Tailspin Toys (Head Office)").customer_tier == "strategic"
    assert get_customer(built_db, "Eric Torres").customer_tier == "standard"


def test_get_product_carries_category(built_db: sqlite3.Connection):
    assert get_product(built_db, "USB missile launcher (Green)").product_category == "Desk Gadgets"


def test_get_customer_case_and_whitespace_insensitive(built_db: sqlite3.Connection):
    customer = get_customer(built_db, "  tailspin toys (head office) ")
    assert customer is not None
    assert customer.customer_id == 1


def test_get_customer_unknown_name_returns_none(built_db: sqlite3.Connection):
    assert get_customer(built_db, "Nonexistent Customer LLC") is None


def test_get_product_exact_match(built_db: sqlite3.Connection):
    product = get_product(built_db, "USB missile launcher (Green)")
    assert product is not None
    assert product.product_id == 1
    assert product.list_price == 25.00


def test_get_product_case_and_whitespace_insensitive(built_db: sqlite3.Connection):
    product = get_product(built_db, "  usb MISSILE launcher (GREEN)  ")
    assert product is not None
    assert product.product_id == 1


def test_get_product_unknown_name_returns_none(built_db: sqlite3.Connection):
    assert get_product(built_db, "Nonexistent Widget") is None


# --- get_deals ---------------------------------------------------------------


def test_get_deals_returns_every_deal_including_expired(built_db: sqlite3.Connection):
    deals = get_deals(built_db)
    ids = [deal.deal_id for deal in deals]
    assert ids == sorted(ids) and len(ids) == 11
    assert any(deal.end_date < AS_OF for deal in deals), (
        "expired deals must be returned too - the engine turns them into levers"
    )


# --- lookups by id and by alias ---------------------------------------------


def test_get_by_id(built_db: sqlite3.Connection):
    assert get_customer_by_id(built_db, 5).customer_name == "Wingtip Toys (Head Office)"
    assert get_product_by_id(built_db, 12).product_category == "Ride-On"
    assert get_customer_by_id(built_db, 999) is None
    assert get_product_by_id(built_db, 999) is None


def test_find_customer_exact_name_then_alias(built_db: sqlite3.Connection):
    assert find_customer(built_db, "Eric Torres").customer_id == 8
    assert find_customer(built_db, "wt retail").customer_id == 5  # alias, case-insensitive
    assert find_customer(built_db, "  Tailspin HQ ").customer_id == 1  # alias, whitespace-insensitive
    assert find_customer(built_db, "Tailspin Toys (Nowhere)") is None  # no fuzzy matching


def test_find_product_exact_name_then_alias(built_db: sqlite3.Connection):
    assert find_product(built_db, "Office cube periscope (Black)").product_id == 2
    assert find_product(built_db, "LAUNCHERS").product_id == 1
    assert find_product(built_db, "monster truck") is None  # deliberately not an alias: ambiguous


# --- search_customers / search_products (deterministic token search) --------


def _ids(hits):
    return [
        (h.record.product_id if hasattr(h.record, "product_id") else h.record.customer_id, h.full_match) for h in hits
    ]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("USB missile launcher (Green)", [(1, True)]),  # exact name
        ("LAUNCHERS", [(1, True)]),  # alias
        ("the launchers for our stores", [(1, True)]),  # stopwords + plural, unique full match
        ("the mugs", [(3, True), (4, True)]),  # two full matches -> ambiguous
        ("monster truck", [(6, True), (11, True)]),
        ("RC big wheel truck", [(6, True)]),  # extra token disambiguates
        ("some stuff for the office", [(2, False)]),  # partial only -> a "did you mean?" candidate
        ("Deluxe Rocket Backpack", []),
    ],
)
def test_search_products(built_db: sqlite3.Connection, query, expected):
    assert _ids(search_products(built_db, query)) == expected


@pytest.mark.parametrize(
    "query, expected",
    [
        ("WT Retail", [(5, True)]),
        ("Tailspin Bow Mar", [(2, True)]),
        ("Wingtip stores", [(5, True), (6, True), (7, True)]),
        ("Eric", [(8, True)]),
        ("east coast stores", []),
    ],
)
def test_search_customers(built_db: sqlite3.Connection, query, expected):
    assert _ids(search_customers(built_db, query)) == expected


def test_search_results_are_capped(built_db: sqlite3.Connection):
    assert len(search_products(built_db, "toys", limit=2)) == 2


def test_get_sales_history_ordered_most_recent_first(built_db: sqlite3.Connection):
    history = get_sales_history(built_db, customer_id=1, product_id=1)

    assert len(history) > 1
    dates = [sale.sale_date for sale in history]
    assert dates == sorted(dates, reverse=True)
    assert history[0].sale_date == date(2026, 8, 30)
    assert history[0].unit_price == pytest.approx(25.00)


def test_get_sales_history_no_history_returns_empty(built_db: sqlite3.Connection):
    # customer 11 (Emily Whittle) has zero sales_history rows by design.
    assert get_sales_history(built_db, customer_id=11, product_id=1) == []

from __future__ import annotations

from datetime import date

import pytest

from quote_workflow.catalog.types import CustomerInfo, Deal, ProductInfo, SaleRecord
from quote_workflow.pricing.engine import (
    deal_unit_price,
    describe_deal,
    floor_price,
    historical_reference,
    select_applicable_deal,
)

TODAY = date(2026, 9, 5)

CUSTOMER = CustomerInfo(
    customer_id=1,
    customer_name="Tailspin Toys (Head Office)",
    customer_category="Retail Chain",
    buying_group="Tailspin Toys",
    customer_tier="strategic",
)

PRODUCT = ProductInfo(
    product_id=1,
    product_name="USB missile launcher (Green)",
    list_price=25.00,
    cost_price=14.00,
    product_category="Desk Gadgets",
)


def _deal(
    deal_id: int = 1,
    customer_id: int | None = None,
    buying_group: str | None = None,
    customer_category: str | None = None,
    product_id: int | None = None,
    min_quantity: int | None = None,
    start_date: date = date(2025, 1, 1),
    end_date: date = date(2026, 12, 31),
    discount_pct: float | None = 10.0,
    fixed_unit_price: float | None = None,
) -> Deal:
    return Deal(
        deal_id=deal_id,
        customer_id=customer_id,
        buying_group=buying_group,
        customer_category=customer_category,
        product_id=product_id,
        min_quantity=min_quantity,
        start_date=start_date,
        end_date=end_date,
        discount_pct=discount_pct,
        fixed_unit_price=fixed_unit_price,
    )


def _sale(quantity: int, unit_price: float, sale_date: date, customer_id: int = 1, product_id: int = 1) -> SaleRecord:
    return SaleRecord(
        customer_id=customer_id,
        product_id=product_id,
        sale_date=sale_date,
        quantity=quantity,
        unit_price=unit_price,
    )


# --- floor_price -----------------------------------------------------------


@pytest.mark.parametrize(
    "cost_price, min_margin_pct, expected",
    [
        (14.00, 15.0, 14.00 / 0.85),
        (100.00, 50.0, 200.00),
        (10.00, 0.0, 10.00),
    ],
)
def test_floor_price(cost_price, min_margin_pct, expected):
    assert floor_price(cost_price, min_margin_pct) == pytest.approx(expected)


# --- select_applicable_deal -------------------------------------------------


def test_customer_specific_deal_beats_buying_group_and_category():
    customer_deal = _deal(deal_id=1, customer_id=1, product_id=1, discount_pct=10.0)
    group_deal = _deal(deal_id=2, buying_group="Tailspin Toys", product_id=1, discount_pct=8.0)
    category_deal = _deal(deal_id=3, customer_category="Retail Chain", discount_pct=3.0)

    chosen = select_applicable_deal(CUSTOMER, PRODUCT, 20, [group_deal, category_deal, customer_deal], TODAY)
    assert chosen is customer_deal


def test_buying_group_deal_beats_category_deal():
    group_deal = _deal(deal_id=2, buying_group="Tailspin Toys", product_id=1, discount_pct=8.0)
    category_deal = _deal(deal_id=3, customer_category="Retail Chain", discount_pct=3.0)

    chosen = select_applicable_deal(CUSTOMER, PRODUCT, 20, [category_deal, group_deal], TODAY)
    assert chosen is group_deal


def test_expired_deal_is_excluded():
    expired = _deal(start_date=date(2024, 1, 1), end_date=date(2024, 6, 30))
    assert select_applicable_deal(CUSTOMER, PRODUCT, 20, [expired], TODAY) is None


def test_not_yet_started_deal_is_excluded():
    future = _deal(start_date=date(2027, 1, 1), end_date=date(2027, 12, 31))
    assert select_applicable_deal(CUSTOMER, PRODUCT, 20, [future], TODAY) is None


def test_min_quantity_excludes_below_threshold_and_includes_at_and_above():
    deal = _deal(customer_id=1, product_id=1, min_quantity=50, fixed_unit_price=32.00, discount_pct=None)

    assert select_applicable_deal(CUSTOMER, PRODUCT, 49, [deal], TODAY) is None
    assert select_applicable_deal(CUSTOMER, PRODUCT, 50, [deal], TODAY) is deal
    assert select_applicable_deal(CUSTOMER, PRODUCT, 51, [deal], TODAY) is deal


def test_product_id_none_matches_any_product():
    other_product = ProductInfo(
        product_id=99, product_name="Anything", list_price=10.0, cost_price=5.0, product_category="Misc"
    )
    category_wide = _deal(customer_category="Retail Chain", product_id=None, discount_pct=3.0)

    assert select_applicable_deal(CUSTOMER, other_product, 1, [category_wide], TODAY) is category_wide


def test_equal_specificity_ties_broken_by_lowest_resulting_price():
    cheaper = _deal(deal_id=1, customer_id=1, product_id=1, discount_pct=20.0)
    pricier = _deal(deal_id=2, customer_id=1, product_id=1, discount_pct=5.0)

    chosen = select_applicable_deal(CUSTOMER, PRODUCT, 20, [pricier, cheaper], TODAY)
    assert chosen is cheaper


def test_no_matching_deals_returns_none():
    unrelated = _deal(customer_id=999, product_id=999)
    assert select_applicable_deal(CUSTOMER, PRODUCT, 20, [unrelated], TODAY) is None


# --- deal_unit_price ---------------------------------------------------------


def test_deal_unit_price_discount_pct():
    deal = _deal(discount_pct=10.0, fixed_unit_price=None)
    assert deal_unit_price(deal, 25.00) == pytest.approx(22.50)


def test_deal_unit_price_fixed_price_ignores_discount():
    deal = _deal(discount_pct=None, fixed_unit_price=32.00)
    assert deal_unit_price(deal, 45.00) == 32.00


# --- describe_deal ------------------------------------------------------------


def test_describe_deal_customer_specific_discount():
    deal = _deal(deal_id=1, customer_id=1, discount_pct=10.0)
    assert describe_deal(deal) == "customer-specific 10% discount (deal #1)"


def test_describe_deal_unrestricted_fixed_price_with_quantity():
    deal = _deal(deal_id=6, min_quantity=50, fixed_unit_price=32.00, discount_pct=None)
    assert describe_deal(deal) == "unrestricted fixed price $32.00 for orders of 50+ (deal #6)"


# --- historical_reference -----------------------------------------------------


def test_no_history_returns_zero_sample():
    ref = historical_reference(1, 1, [], quantity=10)
    assert ref.sample_size == 0
    assert ref.weighted_average_price is None
    assert ref.median_price is None
    assert ref.similar_quantity_price is None


def test_weighted_average_is_quantity_weighted_not_plain_mean():
    sales = [
        _sale(quantity=10, unit_price=20.00, sale_date=date(2026, 1, 1)),
        _sale(quantity=90, unit_price=30.00, sale_date=date(2026, 2, 1)),
    ]
    ref = historical_reference(1, 1, sales, quantity=50)
    plain_mean = (20.00 + 30.00) / 2
    weighted = (10 * 20.00 + 90 * 30.00) / 100
    assert ref.weighted_average_price == pytest.approx(weighted)
    assert ref.weighted_average_price != pytest.approx(plain_mean)


def test_median_price_odd_and_even_sample_sizes():
    odd = [
        _sale(quantity=1, unit_price=10.0, sale_date=date(2026, 1, 1)),
        _sale(quantity=1, unit_price=30.0, sale_date=date(2026, 2, 1)),
        _sale(quantity=1, unit_price=20.0, sale_date=date(2026, 3, 1)),
    ]
    assert historical_reference(1, 1, odd, quantity=1).median_price == 20.0

    even = odd + [_sale(quantity=1, unit_price=40.0, sale_date=date(2026, 4, 1))]
    assert historical_reference(1, 1, even, quantity=1).median_price == 25.0


def test_similar_quantity_price_includes_band_boundaries_and_excludes_outside():
    sales = [
        _sale(quantity=10, unit_price=25.00, sale_date=date(2026, 1, 1)),  # 0.5x boundary - included
        _sale(quantity=40, unit_price=27.00, sale_date=date(2026, 2, 1)),  # 2x boundary - included
        _sale(quantity=9, unit_price=99.00, sale_date=date(2026, 3, 1)),  # just below 0.5x - excluded
        _sale(quantity=41, unit_price=1.00, sale_date=date(2026, 4, 1)),  # just above 2x - excluded
    ]
    ref = historical_reference(1, 1, sales, quantity=20)
    assert ref.similar_quantity_price == pytest.approx((25.00 + 27.00) / 2)


def test_similar_quantity_price_is_none_when_nothing_qualifies():
    sales = [_sale(quantity=1000, unit_price=25.00, sale_date=date(2026, 1, 1))]
    ref = historical_reference(1, 1, sales, quantity=1)
    assert ref.similar_quantity_price is None


def test_most_recent_is_picked_by_date_not_list_order():
    sales = [
        _sale(quantity=1, unit_price=25.00, sale_date=date(2026, 6, 1)),
        _sale(quantity=1, unit_price=99.00, sale_date=date(2026, 1, 1)),
        _sale(quantity=1, unit_price=30.00, sale_date=date(2026, 8, 1)),
    ]
    ref = historical_reference(1, 1, sales, quantity=1)
    assert ref.most_recent_price == 30.00
    assert ref.most_recent_date == date(2026, 8, 1)


def test_only_exact_customer_product_pair_counted():
    sales = [
        _sale(quantity=1, unit_price=25.00, sale_date=date(2026, 1, 1), customer_id=1, product_id=1),
        _sale(quantity=1, unit_price=999.00, sale_date=date(2026, 1, 1), customer_id=2, product_id=1),
        _sale(quantity=1, unit_price=999.00, sale_date=date(2026, 1, 1), customer_id=1, product_id=2),
    ]
    ref = historical_reference(1, 1, sales, quantity=1)
    assert ref.sample_size == 1
    assert ref.most_recent_price == 25.00

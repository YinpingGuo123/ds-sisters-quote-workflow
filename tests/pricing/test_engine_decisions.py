"""Engine v2: price_line / price_quote.

Fixture numbers are chosen so every branch has a distinct, hand-checkable
answer. Product: list $25, cost $14. Floors: 15% -> 16.4706, 12% -> 15.9091,
18% -> 17.0732.
"""

from __future__ import annotations

from datetime import date

import pytest

from quote_workflow.catalog.types import CustomerInfo, Deal, ProductInfo, SaleRecord
from quote_workflow.contracts.enums import PricingStatus
from quote_workflow.pricing.engine import price_line, price_quote
from quote_workflow.pricing.policy import PricingPolicy
from quote_workflow.pricing.types import LinePricing

TODAY = date(2026, 9, 5)

POLICY = PricingPolicy(
    minimum_margin_pct=15.0,
    max_auto_discount_pct=20.0,
    volume_discounts=[
        {"min_quantity": 50, "discount_pct": 3},
        {"min_quantity": 100, "discount_pct": 6},
        {"min_quantity": 250, "discount_pct": 10},
    ],
    term_discounts=[
        {"min_contract_months": 12, "discount_pct": 2},
        {"min_contract_months": 24, "discount_pct": 4},
    ],
    segments=[
        {
            "customer_category": "Retail Chain",
            "customer_tier": "strategic",
            "min_margin_pct": 12,
            "max_auto_discount_pct": 20,
        },
        {"customer_category": "Retail Chain", "min_margin_pct": 15, "max_auto_discount_pct": 15},
        {"customer_category": "Reseller", "min_margin_pct": 18, "max_auto_discount_pct": 10},
    ],
)

PREFERRED = CustomerInfo(1, "Tailspin (Bow Mar)", "Retail Chain", "Tailspin Toys", "preferred")  # floor 16.4706, cap 15
STRATEGIC = CustomerInfo(2, "Tailspin HQ", "Retail Chain", "Tailspin Toys", "strategic")  # floor 15.9091, cap 20
RESELLER = CustomerInfo(3, "Eric Torres", "Reseller", None, "standard")  # floor 17.0732, cap 10

PRODUCT = ProductInfo(1, "USB missile launcher (Green)", 25.00, 14.00, "Desk Gadgets")
FLOOR_15 = 14.0 / 0.85


def _deal(**overrides) -> Deal:
    base = dict(
        deal_id=1,
        customer_id=None,
        buying_group=None,
        customer_category=None,
        product_id=1,
        min_quantity=None,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 12, 31),
        discount_pct=None,
        fixed_unit_price=None,
    )
    return Deal(**{**base, **overrides})


def _line(customer=PREFERRED, quantity=10, deals=(), history=(), **kwargs) -> LinePricing:
    return price_line(customer, PRODUCT, quantity, list(deals), list(history), POLICY, TODAY, **kwargs)


# --- standard pricing: list, ladders, levers --------------------------------


def test_list_price_when_nothing_applies():
    line = _line()
    assert line.status == PricingStatus.APPROVED
    assert line.status_reason == "no_request"
    assert line.recommended_unit_price == line.final_unit_price == 25.0
    assert (line.volume_discount_pct, line.term_discount_pct) == (0.0, 0.0)
    assert line.deal_kind is None and line.counter_unit_price is None
    assert line.margin_pct == pytest.approx(44.0)
    assert not line.floor_applied


def test_segment_guardrails_are_reported_on_the_line():
    assert (_line(STRATEGIC).min_margin_pct, _line(STRATEGIC).max_auto_discount_pct) == (12, 20)
    assert (_line(RESELLER).min_margin_pct, _line(RESELLER).max_auto_discount_pct) == (18, 10)
    assert _line(RESELLER).price_floor == pytest.approx(14.0 / 0.82)


@pytest.mark.parametrize(
    "quantity, months, expected",
    [
        (100, None, 25 * 0.94),  # volume only
        (10, 24, 25 * 0.96),  # term only
        (100, 12, 25 * 0.92),  # both stack on standard pricing
        (49, 11, 25.0),  # just under both thresholds
    ],
)
def test_ladders_apply_to_standard_pricing(quantity, months, expected):
    line = _line(quantity=quantity, contract_months=months)
    assert line.standard_unit_price == pytest.approx(expected)
    assert line.recommended_unit_price == pytest.approx(expected)


def test_levers_point_at_the_next_tiers_with_engine_prices():
    line = _line(quantity=60, contract_months=None)  # in the 3% tier, no term
    kinds = {lever.kind: lever for lever in line.levers}
    assert kinds["next_volume_tier"].threshold == 100
    assert kinds["next_volume_tier"].unit_price == pytest.approx(25 * 0.94)
    assert kinds["next_term_tier"].threshold == 12
    # Term lever keeps the volume discount the customer already has.
    assert kinds["next_term_tier"].unit_price == pytest.approx(25 * (1 - 0.05))


def test_no_ladder_levers_at_the_top_of_both_ladders():
    line = _line(quantity=250, contract_months=24)
    assert line.levers == ()


# --- deals ------------------------------------------------------------------


def test_promotional_deal_replaces_ladders_and_has_no_ladder_levers():
    category_deal = _deal(customer_category="Retail Chain", discount_pct=3.0)
    line = _line(quantity=100, deals=[category_deal])
    assert line.deal_kind == "promotional"
    assert line.recommended_unit_price == pytest.approx(25 * 0.97)  # not the 6% volume tier
    assert line.volume_discount_pct == 6.0  # still reported as a fact
    assert line.levers == ()


def test_promotional_deal_below_floor_is_clamped_and_still_approved():
    group_deal = _deal(buying_group="Tailspin Toys", discount_pct=70.0)  # $7.50
    line = _line(deals=[group_deal])
    assert line.deal_kind == "promotional"
    assert line.floor_applied
    assert line.recommended_unit_price == pytest.approx(FLOOR_15)
    assert line.status == PricingStatus.APPROVED
    assert line.margin_pct == pytest.approx(15.0)


@pytest.mark.parametrize(
    "deal",
    [
        _deal(customer_id=1, discount_pct=70.0),  # customer-specific -> $7.50
        _deal(fixed_unit_price=7.50),  # fixed price -> $7.50
    ],
)
def test_contractual_deal_below_floor_is_honored_and_escalated(deal):
    line = _line(deals=[deal])
    assert line.deal_kind == "contractual"
    assert not line.floor_applied
    assert line.recommended_unit_price == pytest.approx(7.50)
    assert line.final_unit_price == line.recommended_unit_price
    assert line.status == PricingStatus.ESCALATION_REQUIRED
    assert line.status_reason == "contract_below_margin_floor"
    assert line.counter_unit_price is None
    assert line.margin_pct < line.min_margin_pct


def test_contractual_deal_below_floor_escalates_even_if_customer_asks_for_more():
    line = _line(deals=[_deal(customer_id=1, discount_pct=70.0)], requested_unit_price=20.0)
    assert line.status == PricingStatus.ESCALATION_REQUIRED
    assert line.status_reason == "contract_below_margin_floor"


def test_contractual_deal_above_floor_is_ordinary():
    line = _line(deals=[_deal(customer_id=1, discount_pct=10.0)])
    assert line.deal_kind == "contractual"
    assert line.status == PricingStatus.APPROVED
    assert line.recommended_unit_price == pytest.approx(22.5)


def test_expired_deal_surfaces_as_a_lever_not_a_price():
    expired = _deal(customer_id=1, discount_pct=20.0, start_date=date(2023, 1, 1), end_date=date(2023, 12, 31))
    line = _line(deals=[expired])
    assert line.applicable_deal is None
    assert line.recommended_unit_price == 25.0
    expired_levers = [lever for lever in line.levers if lever.kind == "expired_deal"]
    assert len(expired_levers) == 1
    assert expired_levers[0].unit_price == pytest.approx(20.0)
    assert "2023-12-31" in expired_levers[0].description


# --- the customer's request -------------------------------------------------


def test_request_at_or_above_recommended_is_approved_at_recommended():
    line = _line(requested_unit_price=30.0)
    assert line.status == PricingStatus.APPROVED
    assert line.status_reason == "requested_at_or_above_recommended"
    assert line.final_unit_price == 25.0  # never quote above our own price
    assert line.requested_discount_pct == pytest.approx(-20.0)


def test_request_within_cap_is_approved_at_requested():
    line = _line(requested_unit_price=22.0)  # 12% off, cap 15, margin 36%
    assert line.status == PricingStatus.APPROVED
    assert line.status_reason == "requested_within_policy"
    assert line.final_unit_price == 22.0
    assert line.discount_pct == pytest.approx(12.0)


def test_request_beyond_cap_but_above_floor_escalates_with_a_counter():
    line = _line(requested_unit_price=20.0)  # 20% off > cap 15; margin 30% >= 15
    assert line.status == PricingStatus.ESCALATION_REQUIRED
    assert line.status_reason == "requested_exceeds_auto_discount_cap"
    assert line.counter_unit_price == pytest.approx(25 * 0.85)  # best auto-approvable
    assert line.final_unit_price == line.counter_unit_price
    assert line.requested_unit_price == 20.0  # the ask is preserved as a fact


def test_request_below_floor_gets_a_counter():
    line = _line(requested_unit_price=15.0)  # margin 6.7% < 15
    assert line.status == PricingStatus.COUNTER_RECOMMENDED
    assert line.status_reason == "requested_below_margin_floor"
    assert line.counter_unit_price == pytest.approx(25 * 0.85)
    assert line.margin_at_requested_pct == pytest.approx(6.6667, abs=1e-3)


def test_request_exactly_at_floor_is_not_treated_as_below_floor():
    line = _line(requested_unit_price=FLOOR_15)
    assert line.status_reason != "requested_below_margin_floor"
    assert line.status == PricingStatus.ESCALATION_REQUIRED  # 34% off list is beyond the cap


def test_counter_never_exceeds_recommended_when_a_deal_is_already_lower():
    # Deal price 22.50 is above the 15%-off cap price 21.25, so the counter is 21.25.
    line = _line(deals=[_deal(customer_id=1, discount_pct=10.0)], requested_unit_price=15.0)
    assert line.counter_unit_price == pytest.approx(21.25)
    # But with a deal at 18.00 the counter is the deal price itself, not a higher cap price.
    line = _line(deals=[_deal(customer_id=1, discount_pct=28.0)], requested_unit_price=15.0)
    assert line.counter_unit_price == pytest.approx(18.0)


def test_segment_cap_changes_the_verdict_for_the_same_request():
    ask = 20.0  # 20% off
    assert _line(STRATEGIC, requested_unit_price=ask).status == PricingStatus.APPROVED  # cap 20
    assert _line(PREFERRED, requested_unit_price=ask).status == PricingStatus.ESCALATION_REQUIRED  # cap 15
    assert _line(RESELLER, requested_unit_price=ask).status == PricingStatus.ESCALATION_REQUIRED  # cap 10


def test_reseller_floor_is_higher():
    line = _line(RESELLER, requested_unit_price=16.8)  # margin 16.7%: fine for retail, below reseller's 18%
    assert line.status == PricingStatus.COUNTER_RECOMMENDED


def test_quote_level_discount_becomes_a_requested_price():
    line = _line(requested_discount_pct=10.0)
    assert line.requested_unit_price == pytest.approx(22.5)
    assert line.status == PricingStatus.APPROVED and line.final_unit_price == pytest.approx(22.5)


def test_line_level_price_beats_quote_level_discount():
    line = _line(requested_unit_price=24.0, requested_discount_pct=10.0)
    assert line.requested_unit_price == 24.0


# --- competitor price: facts only -------------------------------------------


def test_competitor_price_does_not_change_the_decision():
    with_competitor = _line(competitor_price=20.0)
    without = _line()
    assert with_competitor.status == without.status
    assert with_competitor.final_unit_price == without.final_unit_price
    assert with_competitor.competitor_beatable is True
    assert with_competitor.margin_at_competitor_pct == pytest.approx(30.0)


def test_competitor_below_floor_is_not_beatable():
    line = _line(competitor_price=10.0)
    assert line.competitor_beatable is False
    assert _line().competitor_beatable is None


# --- history ----------------------------------------------------------------


def test_history_is_carried_through():
    sales = [SaleRecord(1, 1, date(2026, 3, 1), 10, 24.0), SaleRecord(9, 1, date(2026, 3, 1), 10, 1.0)]
    line = _line(history=sales)
    assert line.historical.sample_size == 1  # only this customer's rows
    assert line.historical.most_recent_price == 24.0


# --- quote roll-up ----------------------------------------------------------


def test_quote_totals_and_blended_margin():
    a = _line(quantity=10)  # 10 x 25.00, cost 14
    b = _line(quantity=100, requested_unit_price=22.0)  # 100 x 22.00
    quote = price_quote([a, b])
    assert quote.status == PricingStatus.APPROVED
    assert quote.total_list_value == pytest.approx(110 * 25)
    assert quote.total_quoted_value == pytest.approx(250 + 2200)
    assert quote.total_discount_pct == pytest.approx((2750 - 2450) / 2750 * 100)
    assert quote.blended_margin_pct == pytest.approx((2450 - 110 * 14) / 2450 * 100)
    assert quote.unresolved_lines == 0


def test_quote_status_is_the_worst_line_status():
    approved = _line()
    counter = _line(requested_unit_price=15.0)
    escalate = _line(requested_unit_price=20.0)
    assert price_quote([approved]).status == PricingStatus.APPROVED
    assert price_quote([approved, counter]).status == PricingStatus.COUNTER_RECOMMENDED
    assert price_quote([approved, counter, escalate]).status == PricingStatus.ESCALATION_REQUIRED


def test_unresolved_lines_make_the_quote_insufficient_data():
    quote = price_quote([_line()], unresolved_lines=1)
    assert quote.status == PricingStatus.INSUFFICIENT_DATA
    assert quote.total_quoted_value == 250.0  # priced lines still total


def test_empty_quote_is_insufficient_data():
    quote = price_quote([])
    assert quote.status == PricingStatus.INSUFFICIENT_DATA
    assert quote.blended_margin_pct is None
    assert quote.total_quoted_value == 0.0


# --- invariants -------------------------------------------------------------


@pytest.mark.parametrize("customer", [PREFERRED, STRATEGIC, RESELLER])
@pytest.mark.parametrize("requested", [None, 5.0, 15.0, 17.5, 20.0, 22.0, 25.0, 40.0])
@pytest.mark.parametrize("quantity", [1, 50, 250])
@pytest.mark.parametrize(
    "deals",
    [[], [_deal(customer_category="Retail Chain", discount_pct=3.0)], [_deal(customer_id=1, discount_pct=70.0)]],
)
def test_invariants(customer, requested, quantity, deals):
    line = _line(customer, quantity=quantity, deals=deals, requested_unit_price=requested)

    if line.status_reason == "contract_below_margin_floor":
        assert line.final_unit_price < line.price_floor
        assert line.status == PricingStatus.ESCALATION_REQUIRED
    else:
        # Nothing the engine commits to on its own is ever below the floor.
        assert line.final_unit_price >= line.price_floor - 1e-9
        assert line.margin_pct >= line.min_margin_pct - 1e-9

    if line.status == PricingStatus.APPROVED:
        assert line.counter_unit_price is None
        assert line.final_unit_price <= line.recommended_unit_price + 1e-9
        if requested is not None:
            assert (
                line.discount_pct <= line.max_auto_discount_pct + 1e-9
                or line.final_unit_price == line.recommended_unit_price
            )
    else:
        if line.counter_unit_price is not None:
            assert line.price_floor - 1e-9 <= line.counter_unit_price <= line.recommended_unit_price + 1e-9
            assert line.final_unit_price == line.counter_unit_price

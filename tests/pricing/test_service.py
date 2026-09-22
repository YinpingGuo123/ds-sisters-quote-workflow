"""price_request(): catalog inputs -> engine -> PricingDecision.

Expected numbers are hand-computed from config/policy.yaml and data/reference/:
- Superhero action jacket: list 30.00, cost 19.50; Philip Walker is a Reseller
  (floor 18%, cap 10%).
- DBA joke mug: list 13.00, cost 7.00; Tailspin branch is Retail Chain /
  preferred (floor 15%, cap 15%); buying-group deal #2 = 8% off -> 11.96.
- Office cube periscope: list 18.50, cost 11.00; Eric Torres is a Reseller,
  floor price = 11 / 0.82 = 13.4146; cap price = 18.50 * 0.90 = 16.65.
"""

from __future__ import annotations

from datetime import date

import pytest

from quote_workflow.catalog.resolution import resolve
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import PricingStatus, ResolutionStatus
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest
from quote_workflow.pricing.policy import load_policy
from quote_workflow.pricing.service import price_request

AS_OF = date(2026, 9, 5)
ADDRESS = Address(line1="1 Main St", city="Springfield", country="US")


def _request(customer: str, lines: list[QuoteLine], **kwargs) -> QuoteRequest:
    return QuoteRequest(
        customer_name=customer, lines=lines, billing_address=ADDRESS, shipping_address=ADDRESS, **kwargs
    )


def test_standard_quote_is_approved_at_list_with_rationale_and_levers(built_db):
    request = resolve(
        built_db, _request("Philip Walker", [QuoteLine(product_name="Superhero action jacket (Blue) M", quantity=10)])
    )
    decision = price_request(built_db, request, as_of_date=AS_OF)

    assert decision.status == PricingStatus.APPROVED
    assert decision.issues == [] and decision.warnings == []
    assert decision.policy_version == load_policy().version
    assert decision.as_of_date == AS_OF
    [line] = decision.lines
    assert line.line_number == 1
    assert line.final_unit_price == pytest.approx(30.00)
    assert line.line_total == pytest.approx(300.00)
    assert decision.total_quoted_value == pytest.approx(300.00)
    assert [lever.kind for lever in line.levers] == ["next_volume_tier", "next_term_tier"]
    assert line.levers[0].id == "1:next_volume_tier"
    assert line.rationale[0] == "standard pricing at list price $30.00; no volume or term tier reached"
    assert line.rationale[-1] == "final $30.00 per unit: 0.0% off list, 35.0% margin"


def test_buying_group_deal_is_named_in_the_rationale(built_db):
    request = resolve(
        built_db,
        _request(
            "Tailspin Toys (Hambleton, WV)",
            [QuoteLine(product_name="DBA joke mug - SELECT caffeine FROM mug (Black)", quantity=35)],
        ),
    )
    [line] = price_request(built_db, request, as_of_date=AS_OF).lines
    assert line.final_unit_price == pytest.approx(11.96)
    assert line.deal_kind == "promotional"
    assert line.rationale[0].startswith("promotional deal applied: buying-group (Tailspin Toys) 8% discount")


def test_below_floor_request_counters_and_warns(built_db):
    request = resolve(
        built_db,
        _request(
            "Eric Torres",
            [QuoteLine(product_name="Office cube periscope (Black)", quantity=10, requested_unit_price=12.0)],
        ),
    )
    decision = price_request(built_db, request, as_of_date=AS_OF)

    assert decision.status == PricingStatus.COUNTER_RECOMMENDED
    [line] = decision.lines
    assert line.counter_unit_price == pytest.approx(16.65)
    assert line.final_unit_price == pytest.approx(16.65)
    assert any("below the margin floor" in sentence for sentence in line.rationale)
    # Eric also had a 15% periscope deal that ended in 2024 (deal #5) - surfaced so the reviewer knows why he asks.
    assert decision.warnings == [
        "Line 1 (Office cube periscope (Black)): requested price below the margin floor; counter $16.65 recommended",
        "Line 1 (Office cube periscope (Black)): an expired deal would have applied "
        "(expired 2024-06-30: customer-specific 15% discount (deal #5)); the customer may expect it",
    ]


def test_multi_line_quote_takes_worst_status_and_numbers_lines_by_request_position(built_db):
    request = resolve(
        built_db,
        _request(
            "Tailspin Toys (Head Office)",
            [
                QuoteLine(product_name="USB missile launcher (Green)", quantity=100),
                QuoteLine(
                    product_name="DBA joke mug - SELECT caffeine FROM mug (Black)",
                    quantity=200,
                    requested_unit_price=10.0,
                ),
            ],
            contract_months=12,
        ),
    )
    decision = price_request(built_db, request, as_of_date=AS_OF)

    assert decision.status == PricingStatus.ESCALATION_REQUIRED
    assert [line.line_number for line in decision.lines] == [1, 2]
    assert decision.lines[0].status == PricingStatus.APPROVED  # deal #1: 25 * 0.9 = 22.50
    assert decision.lines[0].final_unit_price == pytest.approx(22.50)
    assert decision.lines[1].status == PricingStatus.ESCALATION_REQUIRED  # $10 on $13 = 23% off > 20% strategic cap
    assert decision.warnings[0].startswith("Line 2 (DBA joke mug")


def test_unpriceable_request_still_returns_a_decision(built_db):
    request = resolve(
        built_db,
        _request("Tailspin Toys (Head Office)", [QuoteLine(product_name="Deluxe Rocket Backpack", quantity=5)]),
    )
    assert request.lines[0].product_status == ResolutionStatus.NOT_FOUND

    decision = price_request(built_db, request, as_of_date=AS_OF)
    assert decision.status == PricingStatus.INSUFFICIENT_DATA
    assert decision.lines == []
    assert decision.unresolved_lines == 1
    assert decision.issues == ["line 1: product 'Deluxe Rocket Backpack' not found"]
    assert decision.warnings == ["unpriced: line 1: product 'Deluxe Rocket Backpack' not found"]


def test_decision_round_trips_through_json(built_db):
    request = resolve(
        built_db, _request("Philip Walker", [QuoteLine(product_name="Superhero action jacket (Blue) M", quantity=10)])
    )
    decision = price_request(built_db, request, as_of_date=AS_OF)
    restored = decision.model_validate_json(decision.model_dump_json())
    assert restored == decision

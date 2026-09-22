"""Price a complete QuoteRequest: fetch inputs from the catalog, run the
engine on every line, roll up, and translate the engine's dataclasses into
the shared ``PricingDecision``.

This is the only place that both touches the catalog and calls the engine.
It adds two things the engine does not produce: ``rationale`` sentences per
line and ``warnings`` per quote, both generated in code from the engine's
facts, so the portal can explain a price with no LLM involved. No pricing
math here - every number is copied from ``LinePricing`` / ``QuotePricing``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from quote_workflow.catalog.repository import get_customer_by_id, get_deals, get_product_by_id, get_sales_history
from quote_workflow.contracts.enums import PricingStatus
from quote_workflow.contracts.pricing import Lever, LineDecision, PricingDecision
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.pricing.engine import price_line, price_quote
from quote_workflow.pricing.policy import PricingPolicy, load_policy
from quote_workflow.pricing.types import LinePricing, QuotePricing


def _money(value: float) -> str:
    return f"${value:,.2f}"


def lever_id(line_number: int, kind: str) -> str:
    return f"{line_number}:{kind}"


# Plain-language reason for each engine status_reason - the "why" the reviewer reads first.
_REASON_TEXT = {
    "no_request": "no target price was requested; quoted at our recommended price",
    "requested_at_or_above_recommended": (
        "the requested price is at or above our recommended price; quoted at our price"
    ),
    "requested_within_policy": "the requested price is within the auto-approval discount cap and is approved",
    "requested_below_margin_floor": (
        "the requested price is below the margin floor, which nobody can approve; a counter is offered"
    ),
    "requested_exceeds_auto_discount_cap": (
        "the requested discount exceeds the auto-approval cap; needs approval, counter offered"
    ),
    "contract_below_margin_floor": "the contract price is below the current margin floor; honored, but needs approval",
}


def line_rationale(line: LinePricing) -> list[str]:
    """Deterministic sentences explaining how one line was priced, in derivation order."""
    out: list[str] = []
    if line.applicable_deal is not None:
        out.append(
            f"{line.deal_kind} deal applied: {line.deal_description}; {_money(line.recommended_unit_price)} per unit"
        )
    else:
        ladders = []
        if line.volume_discount_pct:
            ladders.append(f"{line.volume_discount_pct:g}% volume discount")
        if line.term_discount_pct:
            ladders.append(f"{line.term_discount_pct:g}% contract-term discount")
        if ladders:
            out.append(
                f"standard pricing: list {_money(line.list_price)} less {' and '.join(ladders)} "
                f"= {_money(line.standard_unit_price)}"
            )
        else:
            out.append(f"standard pricing at list price {_money(line.list_price)}; no volume or term tier reached")
    if line.floor_applied:
        out.append(f"raised to the margin floor {_money(line.price_floor)} ({line.min_margin_pct:g}% minimum margin)")
    if line.requested_unit_price is not None:
        out.append(
            f"customer requested {_money(line.requested_unit_price)} "
            f"({line.requested_discount_pct:.1f}% off list, {line.margin_at_requested_pct:.1f}% margin)"
        )
    out.append(_REASON_TEXT.get(line.status_reason, line.status_reason))
    if line.counter_unit_price is not None:
        out.append(f"counter offer {_money(line.counter_unit_price)}: the lowest price approvable without escalation")
    out.append(
        f"final {_money(line.final_unit_price)} per unit: "
        f"{line.discount_pct:.1f}% off list, {line.margin_pct:.1f}% margin"
    )
    if line.competitor_price is not None:
        out.append(
            f"competitor price {_money(line.competitor_price)} is "
            f"{'above' if line.competitor_beatable else 'below'} our margin floor"
        )
    return out


def quote_warnings(pricing: QuotePricing, issues: list[str]) -> list[str]:
    """Reviewer-facing flags for the whole quote, derived from the engine's facts."""
    out: list[str] = []
    for number, line in enumerate(pricing.lines, start=1):
        label = f"Line {number} ({line.product_name})"
        if line.status == PricingStatus.ESCALATION_REQUIRED:
            out.append(f"{label}: escalation required - {_REASON_TEXT.get(line.status_reason, line.status_reason)}")
        elif line.status == PricingStatus.COUNTER_RECOMMENDED:
            out.append(
                f"{label}: requested price below the margin floor; "
                f"counter {_money(line.counter_unit_price)} recommended"
            )
        if line.floor_applied:
            out.append(f"{label}: price was raised to the margin floor")
        if line.competitor_price is not None and not line.competitor_beatable:
            out.append(
                f"{label}: competitor price {_money(line.competitor_price)} is below our floor and cannot be matched"
            )
        for lever in line.levers:
            if lever.kind == "expired_deal":
                out.append(
                    f"{label}: an expired deal would have applied ({lever.description}); the customer may expect it"
                )
    if pricing.blended_margin_pct is not None and pricing.lines:
        floor = min(line.min_margin_pct for line in pricing.lines)
        if pricing.blended_margin_pct < floor:
            out.append(
                f"blended margin {pricing.blended_margin_pct:.1f}% is below the {floor:g}% floor "
                "(honored contract pricing)"
            )
    out.extend(f"unpriced: {issue}" for issue in issues)
    return out


def _line_decision(number: int, line: LinePricing) -> LineDecision:
    return LineDecision(
        line_number=number,
        product_id=line.product_id,
        product_name=line.product_name,
        quantity=line.quantity,
        status=line.status,
        status_reason=line.status_reason,
        list_price=line.list_price,
        price_floor=line.price_floor,
        min_margin_pct=line.min_margin_pct,
        max_auto_discount_pct=line.max_auto_discount_pct,
        applicable_deal=line.deal_description,
        deal_kind=line.deal_kind,
        volume_discount_pct=line.volume_discount_pct,
        term_discount_pct=line.term_discount_pct,
        recommended_unit_price=line.recommended_unit_price,
        requested_unit_price=line.requested_unit_price,
        counter_unit_price=line.counter_unit_price,
        final_unit_price=line.final_unit_price,
        line_total=line.line_total,
        discount_pct=line.discount_pct,
        margin_pct=line.margin_pct,
        competitor_price=line.competitor_price,
        competitor_beatable=line.competitor_beatable,
        historical_reference=line.historical.summary(),
        levers=[
            Lever(
                id=lever_id(number, lever.kind),
                kind=lever.kind,
                description=lever.description,
                unit_price=lever.unit_price,
                threshold=lever.threshold,
            )
            for lever in line.levers
        ],
        rationale=line_rationale(line),
    )


def price_request(
    conn: sqlite3.Connection,
    request: QuoteRequest,
    policy: PricingPolicy | None = None,
    as_of_date: date | None = None,
) -> PricingDecision:
    """Price every priceable line of ``request`` and roll the quote up.

    A request that is not priceable (unresolved customer, unresolved lines,
    missing quantities) still returns a decision - status
    ``INSUFFICIENT_DATA`` with the issues listed - so a case always has a
    pricing record to show. Lines that can't be priced are counted in
    ``unresolved_lines``; totals cover priced lines only.
    """
    policy = policy or load_policy()
    as_of_date = as_of_date or date.today()
    issues = request.resolution_issues()

    priced: list[LinePricing] = []
    numbers: list[int] = []
    if request.customer_id is not None and any(line.is_priceable for line in request.lines):
        customer = get_customer_by_id(conn, request.customer_id)
        deals = get_deals(conn)
        for number, line in enumerate(request.lines, start=1):
            if not line.is_priceable:
                continue
            product = get_product_by_id(conn, line.product_id)
            history = get_sales_history(conn, customer.customer_id, product.product_id)
            priced.append(
                price_line(
                    customer,
                    product,
                    line.quantity,
                    deals,
                    history,
                    policy,
                    as_of_date,
                    contract_months=request.contract_months,
                    requested_unit_price=line.requested_unit_price,
                    requested_discount_pct=request.requested_discount_pct,
                    competitor_price=line.competitor_price,
                )
            )
            numbers.append(number)

    pricing = price_quote(priced, unresolved_lines=len(request.lines) - len(priced))
    return PricingDecision(
        status=pricing.status,
        issues=issues,
        lines=[_line_decision(number, line) for number, line in zip(numbers, pricing.lines, strict=True)],
        unresolved_lines=pricing.unresolved_lines,
        total_list_value=pricing.total_list_value,
        total_quoted_value=pricing.total_quoted_value,
        total_discount_pct=pricing.total_discount_pct,
        blended_margin_pct=pricing.blended_margin_pct,
        warnings=quote_warnings(pricing, issues),
        as_of_date=as_of_date,
        policy_version=policy.version,
        priced_at=datetime.now(UTC),
    )

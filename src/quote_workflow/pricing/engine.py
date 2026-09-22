"""Deterministic pricing engine.

Critical pricing constraints are plain Python here, not LLM judgment: start
from list price, apply a valid special deal if one exists (else the standard
volume/term ladders), compare the customer's request against the policy
guardrails, and decide approve / counter / escalate. The LLM may explain or
propose alternatives from the facts this module produces, but it never
recalculates them.

Entry points: ``price_line`` prices one quote line and decides its status;
``price_quote`` rolls the lines up. Both are pure functions.

Scope: this module takes already-fetched data as plain dataclasses (see
``catalog.types`` / ``pricing.types``) - it has no database dependency, so
its tests need no DB fixture. ``pricing.service`` fetches the rows through the
catalog and adapts them into these dataclasses.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from quote_workflow.catalog.types import CustomerInfo, Deal, ProductInfo, SaleRecord
from quote_workflow.contracts.enums import PricingStatus
from quote_workflow.pricing.policy import PricingPolicy
from quote_workflow.pricing.types import HistoricalReference, Lever, LinePricing, QuotePricing

# Float noise guard for "is this price at/above the floor" style comparisons,
# so a request of exactly the floor price is never rejected by 1e-15.
_EPS = 1e-9


def floor_price(cost_price: float, min_margin_pct: float) -> float:
    """The minimum unit price that still yields ``min_margin_pct`` margin."""
    return cost_price / (1 - min_margin_pct / 100)


def compute_margin_pct(unit_price: float, cost_price: float) -> float:
    return (unit_price - cost_price) / unit_price * 100


def compute_discount_pct(unit_price: float, list_price: float) -> float:
    """Discount off list price, as a percentage (negative if above list)."""
    return (list_price - unit_price) / list_price * 100


def deal_unit_price(deal: Deal, list_price: float) -> float:
    if deal.fixed_unit_price is not None:
        return deal.fixed_unit_price
    return list_price * (1 - deal.discount_pct / 100)


def _deal_specificity(deal: Deal) -> int:
    return sum(
        restriction is not None
        for restriction in (deal.customer_id, deal.buying_group, deal.customer_category, deal.product_id)
    )


def _deal_scope_matches(customer: CustomerInfo, product: ProductInfo, quantity: int, deal: Deal) -> bool:
    """Everything about a deal except its validity window."""
    return (
        (deal.customer_id is None or deal.customer_id == customer.customer_id)
        and (deal.buying_group is None or deal.buying_group == customer.buying_group)
        and (deal.customer_category is None or deal.customer_category == customer.customer_category)
        and (deal.product_id is None or deal.product_id == product.product_id)
        and (deal.min_quantity is None or quantity >= deal.min_quantity)
    )


def _deal_matches(
    customer: CustomerInfo,
    product: ProductInfo,
    quantity: int,
    deal: Deal,
    as_of_date: date,
) -> bool:
    return deal.start_date <= as_of_date <= deal.end_date and _deal_scope_matches(customer, product, quantity, deal)


def filter_applicable_deals(
    customer: CustomerInfo,
    product: ProductInfo,
    quantity: int,
    deals: list[Deal],
    as_of_date: date,
) -> list[Deal]:
    """All deals that apply to this request, unranked.

    A deal's ``customer_id``/``buying_group``/``customer_category``/``product_id``
    each act as a wildcard when ``None``; every non-null one must match. A
    ``min_quantity`` requires ``quantity >= min_quantity`` (inclusive).

    See ``select_applicable_deal`` for the ranked pick.
    """
    return [deal for deal in deals if _deal_matches(customer, product, quantity, deal, as_of_date)]


def select_applicable_deal(
    customer: CustomerInfo,
    product: ProductInfo,
    quantity: int,
    deals: list[Deal],
    as_of_date: date,
) -> Deal | None:
    """Pick the single best deal that applies to this request, or None.

    Precedence when multiple deals match (not specified verbatim in the
    business spec - this is the deliberate, documented tie-break rule): the
    **most specific** deal wins, ranked by how many of the four restriction
    fields are non-null (e.g. a customer-specific deal beats a buying-group
    deal beats a category-wide deal). Equally specific deals are tie-broken by
    **lowest resulting unit price**, so a tie deterministically favors the
    customer.
    """
    candidates = filter_applicable_deals(customer, product, quantity, deals, as_of_date)
    if not candidates:
        return None
    candidates.sort(key=lambda deal: (-_deal_specificity(deal), deal_unit_price(deal, product.list_price)))
    return candidates[0]


def describe_deal(deal: Deal) -> str:
    """A short factual description of a deal, for LineDecision.applicable_deal."""
    if deal.customer_id is not None:
        scope = "customer-specific"
    elif deal.buying_group is not None:
        scope = f"buying-group ({deal.buying_group})"
    elif deal.customer_category is not None:
        scope = f"category ({deal.customer_category})"
    else:
        scope = "unrestricted"

    if deal.fixed_unit_price is not None:
        price_part = f"fixed price ${deal.fixed_unit_price:.2f}"
    else:
        price_part = f"{deal.discount_pct:g}% discount"

    quantity_part = f" for orders of {deal.min_quantity}+" if deal.min_quantity is not None else ""

    return f"{scope} {price_part}{quantity_part} (deal #{deal.deal_id})"


def historical_reference(
    customer_id: int,
    product_id: int,
    sales_history: list[SaleRecord],
    quantity: int,
) -> HistoricalReference:
    """Simple historical references for the same customer/product pair.

    Only exact customer/product matches - no cross-customer or cross-product
    fallback, and no price elasticity or ML pricing models.
    """
    matches = [sale for sale in sales_history if sale.customer_id == customer_id and sale.product_id == product_id]
    if not matches:
        return HistoricalReference(sample_size=0)

    total_quantity = sum(sale.quantity for sale in matches)
    weighted_average_price = sum(sale.quantity * sale.unit_price for sale in matches) / total_quantity
    median_price = median(sale.unit_price for sale in matches)

    similar = [sale for sale in matches if 0.5 * quantity <= sale.quantity <= 2 * quantity]
    similar_quantity_price = sum(sale.unit_price for sale in similar) / len(similar) if similar else None

    most_recent = max(matches, key=lambda sale: sale.sale_date)

    return HistoricalReference(
        sample_size=len(matches),
        weighted_average_price=weighted_average_price,
        median_price=median_price,
        similar_quantity_price=similar_quantity_price,
        most_recent_price=most_recent.unit_price,
        most_recent_date=most_recent.sale_date,
    )


def _levers(
    customer: CustomerInfo,
    product: ProductInfo,
    quantity: int,
    contract_months: int | None,
    deal: Deal | None,
    deals: list[Deal],
    policy: PricingPolicy,
    as_of_date: date,
) -> tuple[Lever, ...]:
    """Concrete alternatives the advisor may propose, with engine-computed prices.

    Ladder levers only make sense on standard pricing - a deal replaces the
    ladders, so there is no "next tier" to reach while one applies.
    """
    levers: list[Lever] = []
    if deal is None:
        term_pct = policy.term_discount_for(contract_months)
        next_volume = next((t for t in policy.volume_discounts if t.min_quantity > quantity), None)
        if next_volume is not None:
            levers.append(
                Lever(
                    kind="next_volume_tier",
                    description=f"{next_volume.discount_pct:g}% volume discount at {next_volume.min_quantity}+ units",
                    unit_price=product.list_price * (1 - (next_volume.discount_pct + term_pct) / 100),
                    threshold=next_volume.min_quantity,
                )
            )

        volume_pct = policy.volume_discount_for(quantity)
        months = contract_months or 0
        next_term = next((t for t in policy.term_discounts if t.min_contract_months > months), None)
        if next_term is not None:
            levers.append(
                Lever(
                    kind="next_term_tier",
                    description=(
                        f"{next_term.discount_pct:g}% term discount on a {next_term.min_contract_months}-month contract"
                    ),
                    unit_price=product.list_price * (1 - (volume_pct + next_term.discount_pct) / 100),
                    threshold=next_term.min_contract_months,
                )
            )

    # A deal that fits this request in every way except its dates - the
    # customer may well be quoting it, and the rep should know why it's gone.
    for candidate in deals:
        if candidate.end_date < as_of_date and _deal_scope_matches(customer, product, quantity, candidate):
            levers.append(
                Lever(
                    kind="expired_deal",
                    description=f"expired {candidate.end_date.isoformat()}: {describe_deal(candidate)}",
                    unit_price=deal_unit_price(candidate, product.list_price),
                )
            )
    return tuple(levers)


def price_line(
    customer: CustomerInfo,
    product: ProductInfo,
    quantity: int,
    deals: list[Deal],
    sales_history: list[SaleRecord],
    policy: PricingPolicy,
    as_of_date: date,
    *,
    contract_months: int | None = None,
    requested_unit_price: float | None = None,
    requested_discount_pct: float | None = None,
    competitor_price: float | None = None,
) -> LinePricing:
    """Price one quote line and decide its status. Pure; see LinePricing for the facts.

    Decision order (first match wins):

    1. A *contractual* deal (customer-specific or fixed-price) is honored as
       the recommended price even below the floor - but such a line is
       ``ESCALATION_REQUIRED``: nobody auto-approves below floor, and the
       engine will not silently rewrite a contract either.
    2. No request → ``APPROVED`` at the recommended price.
    3. Request at or above recommended → ``APPROVED`` at the recommended
       price (we never quote above our own price).
    4. Request breaks the margin floor → ``COUNTER_RECOMMENDED`` at the best
       auto-approvable price. A human can't approve it either.
    5. Request within the segment's auto-discount cap → ``APPROVED`` at the
       requested price.
    6. Otherwise (beyond the cap, above the floor) → ``ESCALATION_REQUIRED``,
       with the same counter offered as a fallback.

    ``requested_unit_price`` (line-level) takes precedence over
    ``requested_discount_pct`` (quote-level, applied to list price).
    """
    guardrails = policy.guardrails_for(customer.customer_category, customer.customer_tier)
    price_floor = floor_price(product.cost_price, guardrails.min_margin_pct)

    deal = select_applicable_deal(customer, product, quantity, deals, as_of_date)
    volume_pct = policy.volume_discount_for(quantity)
    term_pct = policy.term_discount_for(contract_months)
    standard_unit_price = product.list_price * (1 - (volume_pct + term_pct) / 100)

    if deal is None:
        deal_kind = None
        base_price = standard_unit_price
    else:
        deal_kind = "contractual" if deal.is_contractual else "promotional"
        base_price = deal_unit_price(deal, product.list_price)

    contract_below_floor = deal_kind == "contractual" and base_price < price_floor - _EPS
    if contract_below_floor:
        recommended = base_price  # honored, not clamped
        floor_applied = False
    else:
        recommended = max(base_price, price_floor)
        floor_applied = recommended > base_price + _EPS

    # The customer's ask, normalized to a unit price.
    requested: float | None
    if requested_unit_price is not None:
        requested = requested_unit_price
    elif requested_discount_pct is not None:
        requested = product.list_price * (1 - requested_discount_pct / 100)
    else:
        requested = None
    requested_off_list = compute_discount_pct(requested, product.list_price) if requested is not None else None
    margin_at_requested = compute_margin_pct(requested, product.cost_price) if requested is not None else None

    competitor_beatable = None
    margin_at_competitor = None
    if competitor_price is not None:
        competitor_beatable = competitor_price >= price_floor - _EPS
        margin_at_competitor = compute_margin_pct(competitor_price, product.cost_price)

    # Lowest price the policy lets us commit to without a human: the cap off
    # list, never below the floor, never above what we already recommend.
    best_auto_price = max(
        price_floor,
        min(recommended, product.list_price * (1 - guardrails.max_auto_discount_pct / 100)),
    )

    counter: float | None = None
    if contract_below_floor:
        status, reason, final = PricingStatus.ESCALATION_REQUIRED, "contract_below_margin_floor", recommended
    elif requested is None:
        status, reason, final = PricingStatus.APPROVED, "no_request", recommended
    elif requested >= recommended - _EPS:
        status, reason, final = PricingStatus.APPROVED, "requested_at_or_above_recommended", recommended
    elif margin_at_requested < guardrails.min_margin_pct - _EPS:
        counter = best_auto_price
        status, reason, final = PricingStatus.COUNTER_RECOMMENDED, "requested_below_margin_floor", counter
    elif requested_off_list <= guardrails.max_auto_discount_pct + _EPS:
        status, reason, final = PricingStatus.APPROVED, "requested_within_policy", requested
    else:
        counter = best_auto_price
        status, reason, final = PricingStatus.ESCALATION_REQUIRED, "requested_exceeds_auto_discount_cap", counter

    return LinePricing(
        product_id=product.product_id,
        product_name=product.product_name,
        quantity=quantity,
        list_price=product.list_price,
        cost_price=product.cost_price,
        min_margin_pct=guardrails.min_margin_pct,
        max_auto_discount_pct=guardrails.max_auto_discount_pct,
        price_floor=price_floor,
        applicable_deal=deal,
        deal_description=describe_deal(deal) if deal is not None else None,
        deal_kind=deal_kind,
        volume_discount_pct=volume_pct,
        term_discount_pct=term_pct,
        standard_unit_price=standard_unit_price,
        recommended_unit_price=recommended,
        floor_applied=floor_applied,
        requested_unit_price=requested,
        requested_discount_pct=requested_off_list,
        margin_at_requested_pct=margin_at_requested,
        competitor_price=competitor_price,
        competitor_beatable=competitor_beatable,
        margin_at_competitor_pct=margin_at_competitor,
        status=status,
        status_reason=reason,
        final_unit_price=final,
        counter_unit_price=counter,
        discount_pct=compute_discount_pct(final, product.list_price),
        margin_pct=compute_margin_pct(final, product.cost_price),
        historical=historical_reference(customer.customer_id, product.product_id, sales_history, quantity),
        levers=_levers(customer, product, quantity, contract_months, deal, deals, policy, as_of_date),
    )


# Worst-first: a quote takes the most severe status among its lines.
_STATUS_SEVERITY = {
    PricingStatus.INSUFFICIENT_DATA: 3,
    PricingStatus.ESCALATION_REQUIRED: 2,
    PricingStatus.COUNTER_RECOMMENDED: 1,
    PricingStatus.APPROVED: 0,
}


def price_quote(lines: list[LinePricing], unresolved_lines: int = 0) -> QuotePricing:
    """Roll priced lines up to quote level.

    ``unresolved_lines`` counts lines the caller could not price at all
    (unknown product, missing quantity); any such line makes the quote
    ``INSUFFICIENT_DATA``. Totals cover priced lines only.
    """
    if unresolved_lines > 0 or not lines:
        status = PricingStatus.INSUFFICIENT_DATA
    else:
        status = max((line.status for line in lines), key=_STATUS_SEVERITY.__getitem__)

    total_list = sum(line.quantity * line.list_price for line in lines)
    total_quoted = sum(line.line_total for line in lines)
    total_cost = sum(line.quantity * line.cost_price for line in lines)

    return QuotePricing(
        lines=tuple(lines),
        unresolved_lines=unresolved_lines,
        status=status,
        total_list_value=total_list,
        total_quoted_value=total_quoted,
        total_discount_pct=compute_discount_pct(total_quoted, total_list) if total_list else 0.0,
        blended_margin_pct=compute_margin_pct(total_quoted, total_cost) if total_quoted else None,
    )

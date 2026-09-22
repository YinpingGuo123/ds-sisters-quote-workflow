"""The grounding text: every pricing fact the LLM is allowed to talk about.

Built from the shared ``PricingDecision`` (never from the engine's internals),
formatted so ``validate.py`` can check that any dollar amount or percentage
in the model's answer appears here verbatim.
"""

from __future__ import annotations

from quote_workflow.contracts.pricing import LineDecision, PricingDecision
from quote_workflow.contracts.quote_request import QuoteRequest


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def _line_facts(line: LineDecision) -> str:
    parts = [
        f"Line {line.line_number}: {line.product_name} x {line.quantity}",
        f"  status: {line.status.value} ({line.status_reason})",
        f"  list price {_fmt_money(line.list_price)}; margin floor {_fmt_money(line.price_floor)} "
        f"(min margin {line.min_margin_pct:.1f}%, auto-approval cap {line.max_auto_discount_pct:.1f}% off list)",
        f"  applicable deal: {line.applicable_deal or 'none'}"
        + (f" [{line.deal_kind}]" if line.deal_kind else "")
        + (
            f"; standard ladders: volume {line.volume_discount_pct:.1f}%, term {line.term_discount_pct:.1f}%"
            if line.deal_kind is None
            else ""
        ),
        f"  recommended {_fmt_money(line.recommended_unit_price)}; final {_fmt_money(line.final_unit_price)} "
        f"({line.discount_pct:.1f}% off list, margin {line.margin_pct:.1f}%); line total {_fmt_money(line.line_total)}",
    ]
    if line.requested_unit_price is not None:
        parts.append(f"  customer requested {_fmt_money(line.requested_unit_price)}")
    if line.counter_unit_price is not None:
        parts.append(f"  counter offer: {_fmt_money(line.counter_unit_price)}")
    if line.competitor_price is not None:
        parts.append(
            f"  competitor price {_fmt_money(line.competitor_price)}: "
            f"{'above' if line.competitor_beatable else 'below'} our floor"
        )
    if line.historical_reference:
        parts.append(f"  history: {line.historical_reference}")
    for lever in line.levers:
        parts.append(f"  alternative ({lever.kind}): {lever.description} -> {_fmt_money(lever.unit_price)}")
    parts.extend(f"  engine rationale: {sentence}" for sentence in line.rationale)
    return "\n".join(parts)


def build_facts(request: QuoteRequest, pricing: PricingDecision) -> str:
    header = [
        f"Customer: {request.customer_name}",
        f"Contract term: {request.contract_months or 0} months",
        f"Quote status: {pricing.status.value}",
        f"Pricing policy version: {pricing.policy_version}",
    ]
    if request.requested_discount_pct is not None:
        header.append(f"Customer asked for {request.requested_discount_pct:.1f}% off across the quote")
    if request.requested_delivery_date:
        header.append(f"Requested delivery date: {request.requested_delivery_date.isoformat()}")
    lines = [_line_facts(line) for line in pricing.lines]
    if pricing.unresolved_lines:
        lines.append(f"{pricing.unresolved_lines} line(s) could not be priced: {'; '.join(pricing.issues)}")
    totals = (
        f"Totals: list value {_fmt_money(pricing.total_list_value)}; quoted {_fmt_money(pricing.total_quoted_value)} "
        f"({pricing.total_discount_pct:.1f}% off)"
        + (f"; blended margin {pricing.blended_margin_pct:.1f}%" if pricing.blended_margin_pct is not None else "")
    )
    warnings = ["Engine warnings:"] + [f"  - {w}" for w in pricing.warnings] if pricing.warnings else []
    return "\n".join(header + [""] + lines + ["", totals] + warnings)

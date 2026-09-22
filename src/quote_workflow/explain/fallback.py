"""Deterministic reviewer summary, built in code from the PricingDecision.

Used whenever the LLM is unavailable, not configured, or its output failed
validation - the reviewer always gets a summary, and it never depends on a
network call.
"""

from __future__ import annotations

from quote_workflow.contracts.enums import PricingStatus
from quote_workflow.contracts.pricing import PricingDecision
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.review import ReviewerSummary


def _money(value: float) -> str:
    return f"${value:,.2f}"


def fallback_summary(
    request: QuoteRequest, pricing: PricingDecision, rejected_reason: str | None = None
) -> ReviewerSummary:
    if not pricing.lines:
        summary = "Nothing could be priced: " + "; ".join(pricing.issues) + "."
        return ReviewerSummary(
            summary=summary,
            warnings=list(pricing.warnings),
            attention_items=["Resolve the missing information before this case can be priced."],
            generated_by="fallback",
            rejected_reason=rejected_reason,
        )

    summary = (
        f"{len(pricing.lines)} line(s) priced for {request.customer_name}, "
        f"total {_money(pricing.total_quoted_value)} ({pricing.total_discount_pct:.1f}% off list"
        + (f", blended margin {pricing.blended_margin_pct:.1f}%" if pricing.blended_margin_pct is not None else "")
        + f"). Quote status: {pricing.status.value}."
    )
    rationale = [
        f"Line {line.line_number} ({line.product_name}): {sentence}"
        for line in pricing.lines
        for sentence in line.rationale
    ]

    attention: list[str] = []
    for line in pricing.lines:
        label = f"Line {line.line_number} ({line.product_name})"
        if line.status == PricingStatus.ESCALATION_REQUIRED:
            attention.append(f"{label} needs your approval at {_money(line.final_unit_price)}.")
        elif line.status == PricingStatus.COUNTER_RECOMMENDED:
            attention.append(f"{label}: confirm the counter offer of {_money(line.counter_unit_price)}.")
    if pricing.unresolved_lines:
        attention.append(f"{pricing.unresolved_lines} line(s) could not be priced: " + "; ".join(pricing.issues))
    if not attention:
        attention.append("All lines are within policy; approve if the commercial context is acceptable.")

    return ReviewerSummary(
        summary=summary,
        rationale=rationale,
        warnings=list(pricing.warnings),
        attention_items=attention,
        draft_reply=None,
        generated_by="fallback",
        rejected_reason=rejected_reason,
    )

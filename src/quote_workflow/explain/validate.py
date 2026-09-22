"""Grounding and leakage checks on an LLM-written reviewer summary.

Grounding: every dollar amount and percentage in the summary must appear in
the facts text the model was given - so the LLM cannot compute, round
differently, or invent a number. Leakage: the customer-facing draft must not
contain a cost price, a margin figure, or internal vocabulary. Returns a
rejection reason or None; the caller falls back to the deterministic summary
on any rejection.
"""

from __future__ import annotations

import re

from quote_workflow.contracts.pricing import PricingDecision
from quote_workflow.explain.output import LlmSummary

_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
# "cost-effective" is fine customer language; "our cost" is not - hence the
# hyphen look-ahead. The numeric cost/margin checks are the hard guard anyway.
_INTERNAL_WORDS = re.compile(r"\b(cost(?!-)|margin|floor|escalat\w*|auto-?approv\w*|policy)\b", re.IGNORECASE)


def money_values(text: str) -> set[float]:
    return {round(float(m.replace(",", "")), 2) for m in _MONEY.findall(text)}


def percent_values(text: str) -> set[float]:
    return {round(float(m), 1) for m in _PERCENT.findall(text)}


def validate_summary(candidate: LlmSummary, facts: str, pricing: PricingDecision) -> str | None:
    """Return a rejection reason, or None if the summary is acceptable."""
    allowed_money = money_values(facts)
    allowed_percent = percent_values(facts)
    everything = " ".join(
        [
            candidate.summary,
            *candidate.rationale,
            *candidate.warnings,
            *candidate.attention_items,
            candidate.draft_reply or "",
        ]
    )

    unknown_money = money_values(everything) - allowed_money
    if unknown_money:
        return f"dollar amount not in facts: {sorted(unknown_money)}"
    unknown_percent = percent_values(everything) - allowed_percent
    if unknown_percent:
        return f"percentage not in facts: {sorted(unknown_percent)}"

    if candidate.draft_reply:
        floors = {round(line.price_floor, 2) for line in pricing.lines}
        margins = {round(line.margin_pct, 1) for line in pricing.lines} | {
            round(line.min_margin_pct, 1) for line in pricing.lines
        }
        if money_values(candidate.draft_reply) & floors:
            return "draft_reply leaks a margin-floor price"
        if percent_values(candidate.draft_reply) & margins:
            return "draft_reply leaks a margin figure"
        if match := _INTERNAL_WORDS.search(candidate.draft_reply):
            return f"draft_reply uses internal vocabulary: '{match.group(0)}'"
    return None

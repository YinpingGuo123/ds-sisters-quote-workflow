"""Internal shapes of the pricing engine: every deterministic fact about a
priced line and the quote-level roll-up.

These are the engine's *output* dataclasses; ``pricing.service`` translates
them into the shared ``contracts.pricing`` models. The engine's *inputs*
(customer, product, deals, sales) come from ``catalog.types``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from quote_workflow.catalog.types import Deal
from quote_workflow.contracts.enums import PricingStatus


@dataclass(frozen=True)
class HistoricalReference:
    sample_size: int
    weighted_average_price: float | None = None
    median_price: float | None = None
    similar_quantity_price: float | None = None
    most_recent_price: float | None = None
    most_recent_date: date | None = None

    def summary(self) -> str | None:
        """A short factual sentence for LineDecision.historical_reference."""
        if self.sample_size == 0:
            return None
        parts = [f"{self.sample_size} prior order{'s' if self.sample_size != 1 else ''}"]
        if self.weighted_average_price is not None:
            parts.append(f"weighted avg ${self.weighted_average_price:.2f}")
        if self.median_price is not None:
            parts.append(f"median ${self.median_price:.2f}")
        if self.similar_quantity_price is not None:
            parts.append(f"similar-quantity avg ${self.similar_quantity_price:.2f}")
        if self.most_recent_price is not None and self.most_recent_date is not None:
            parts.append(f"most recent ${self.most_recent_price:.2f} on {self.most_recent_date.isoformat()}")
        return "; ".join(parts)


@dataclass(frozen=True)
class Lever:
    """A concrete, engine-computed alternative the advisor may propose.

    The LLM chooses *which* of these to mention and how to phrase them; it
    never invents the numbers - every unit price here came from the engine.
    """

    kind: str  # "next_volume_tier" | "next_term_tier" | "expired_deal"
    description: str
    unit_price: float
    # What the customer would have to do: quantity for a volume tier, months
    # for a term tier, None for an expired deal (nothing the customer can do).
    threshold: int | None = None


@dataclass(frozen=True)
class LinePricing:
    """Every deterministic fact about one quote line, plus the engine's status.

    Field groups, in the order the engine derives them: identity → policy
    guardrails → deal / standard discounts → recommended price → the
    customer's request and competitor price compared against it → the
    decision (status, final price, counter) → context (history, levers).
    """

    product_id: int
    product_name: str
    quantity: int

    list_price: float
    cost_price: float
    min_margin_pct: float
    max_auto_discount_pct: float
    price_floor: float

    applicable_deal: Deal | None
    deal_description: str | None
    deal_kind: str | None  # "contractual" | "promotional" | None
    volume_discount_pct: float  # ladder value for this quantity (0 if none)
    term_discount_pct: float  # ladder value for the contract term (0 if none)
    standard_unit_price: float  # list price less the ladders - used only when no deal applies

    recommended_unit_price: float
    floor_applied: bool  # a promotional deal / standard price was raised to the floor

    requested_unit_price: float | None
    requested_discount_pct: float | None  # off list, derived from requested_unit_price
    margin_at_requested_pct: float | None

    competitor_price: float | None
    competitor_beatable: bool | None  # competitor price is at or above our floor
    margin_at_competitor_pct: float | None

    status: PricingStatus
    status_reason: str
    final_unit_price: float  # what goes on the quote (recommended / approved request / counter)
    counter_unit_price: float | None  # best auto-approvable price, when the request can't be met
    discount_pct: float  # final price vs list
    margin_pct: float  # at the final price

    historical: HistoricalReference
    levers: tuple[Lever, ...]

    @property
    def line_total(self) -> float:
        return self.quantity * self.final_unit_price


@dataclass(frozen=True)
class QuotePricing:
    lines: tuple[LinePricing, ...]
    unresolved_lines: int  # lines that could not be priced (unknown product, missing quantity)
    status: PricingStatus
    total_list_value: float
    total_quoted_value: float
    total_discount_pct: float
    blended_margin_pct: float | None  # None when nothing could be priced

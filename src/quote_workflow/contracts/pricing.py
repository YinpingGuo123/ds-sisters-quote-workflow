"""The pricing module's output: every deterministic fact about a priced request.

Produced once by ``pricing.service.price_request`` and final from then on -
the reviewer summary, the portal and the quotation read from it, nothing
rewrites a number in it. ``rationale`` and ``warnings`` are plain sentences
generated in code, so the portal can explain a price even with no LLM.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from quote_workflow.contracts.enums import PricingStatus


class Lever(BaseModel):
    """A concrete alternative the engine computed (next volume tier, next term
    tier, an expired deal the customer may still expect). Prices here came
    from the engine, never from an LLM."""

    id: str  # "<line number>:<kind>"
    kind: str  # "next_volume_tier" | "next_term_tier" | "expired_deal"
    description: str
    unit_price: float
    threshold: int | None = None  # quantity or months the customer would need; None for expired deals


class LineDecision(BaseModel):
    line_number: int
    product_id: int
    product_name: str
    quantity: int

    status: PricingStatus
    status_reason: str

    list_price: float
    price_floor: float
    min_margin_pct: float
    max_auto_discount_pct: float

    applicable_deal: str | None  # human-readable deal description, or None
    deal_kind: str | None  # "contractual" | "promotional" | None
    volume_discount_pct: float
    term_discount_pct: float

    recommended_unit_price: float
    requested_unit_price: float | None
    counter_unit_price: float | None
    final_unit_price: float
    line_total: float
    discount_pct: float
    margin_pct: float

    competitor_price: float | None = None
    competitor_beatable: bool | None = None

    historical_reference: str | None = None
    levers: list[Lever] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)  # why this line landed where it did, in order


class PricingDecision(BaseModel):
    status: PricingStatus
    issues: list[str] = Field(default_factory=list)  # from QuoteRequest.resolution_issues()

    lines: list[LineDecision] = Field(default_factory=list)
    unresolved_lines: int = 0
    total_list_value: float = 0.0
    total_quoted_value: float = 0.0
    total_discount_pct: float = 0.0
    blended_margin_pct: float | None = None

    warnings: list[str] = Field(default_factory=list)  # reviewer-facing flags: escalations, floor hits, expired deals
    as_of_date: date
    policy_version: str
    priced_at: datetime

"""Load and validate the business policy from config/policy.yaml.

This module is I/O + validation + *rule lookup* (which ladder tier applies,
which segment's guardrails apply) - no pricing math. ``pricing.engine``
imports ``PricingPolicy``/``load_policy`` from here rather than reading the
YAML file itself, and calls the lookup methods rather than scanning the
ladders on its own, so the "which rule applies" logic is tested once, here.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from quote_workflow.config import POLICY_PATH


class VolumeTier(BaseModel):
    min_quantity: int = Field(gt=0)
    discount_pct: float = Field(ge=0, le=100)


class TermTier(BaseModel):
    min_contract_months: int = Field(gt=0)
    discount_pct: float = Field(ge=0, le=100)


class SegmentGuardrails(BaseModel):
    """Margin floor and auto-approval cap for one customer segment.

    ``customer_tier`` is optional so a row can cover a whole category; a row
    that names both category and tier is more specific and wins.
    """

    customer_category: str
    customer_tier: str | None = None
    min_margin_pct: float = Field(ge=0, le=100)
    max_auto_discount_pct: float = Field(ge=0, le=100)


class PricingPolicy(BaseModel):
    version: str = "unversioned"  # stamped on every PricingDecision so a case says which rules priced it
    minimum_margin_pct: float = Field(ge=0, le=100)
    max_auto_discount_pct: float = Field(ge=0, le=100)
    volume_discounts: list[VolumeTier] = Field(default_factory=list)
    term_discounts: list[TermTier] = Field(default_factory=list)
    segments: list[SegmentGuardrails] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ladders_strictly_increasing(self) -> PricingPolicy:
        # A ladder must climb: each tier needs a higher threshold *and* a
        # higher discount than the one before, otherwise "highest tier met"
        # is ambiguous or a bigger order would earn a smaller discount.
        _check_ladder("volume_discounts", [(t.min_quantity, t.discount_pct) for t in self.volume_discounts])
        _check_ladder("term_discounts", [(t.min_contract_months, t.discount_pct) for t in self.term_discounts])

        keys = [(s.customer_category, s.customer_tier) for s in self.segments]
        if len(keys) != len(set(keys)):
            raise ValueError("segments: duplicate (customer_category, customer_tier) entries")
        return self

    def volume_discount_for(self, quantity: int) -> float:
        """Percentage from the highest volume tier whose min_quantity is met (0 if none)."""
        return _highest_met(quantity, [(t.min_quantity, t.discount_pct) for t in self.volume_discounts])

    def term_discount_for(self, contract_months: int | None) -> float:
        """Percentage from the highest term tier whose min_contract_months is met (0 if none)."""
        if contract_months is None:
            return 0.0
        return _highest_met(contract_months, [(t.min_contract_months, t.discount_pct) for t in self.term_discounts])

    def guardrails_for(self, customer_category: str, customer_tier: str) -> SegmentGuardrails:
        """Most specific matching segment, falling back to the policy-wide defaults.

        Precedence: (category, tier) match > category-only match > the
        policy-wide ``minimum_margin_pct`` / ``max_auto_discount_pct`` defaults.
        """
        category_only = None
        for segment in self.segments:
            if segment.customer_category != customer_category:
                continue
            if segment.customer_tier == customer_tier:
                return segment
            if segment.customer_tier is None:
                category_only = segment
        if category_only is not None:
            return category_only
        return SegmentGuardrails(
            customer_category=customer_category,
            customer_tier=None,
            min_margin_pct=self.minimum_margin_pct,
            max_auto_discount_pct=self.max_auto_discount_pct,
        )


def _check_ladder(name: str, tiers: list[tuple[int, float]]) -> None:
    for (prev_threshold, prev_pct), (threshold, pct) in zip(tiers, tiers[1:], strict=False):
        if threshold <= prev_threshold or pct <= prev_pct:
            raise ValueError(f"{name}: tiers must have strictly increasing thresholds and discounts")


def _highest_met(value: int, tiers: list[tuple[int, float]]) -> float:
    met = [pct for threshold, pct in tiers if value >= threshold]
    return met[-1] if met else 0.0


def load_policy(path: Path = POLICY_PATH) -> PricingPolicy:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PricingPolicy(**data)

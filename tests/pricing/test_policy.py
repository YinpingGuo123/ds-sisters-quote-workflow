from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from quote_workflow.config import POLICY_PATH
from quote_workflow.pricing.policy import PricingPolicy, SegmentGuardrails, load_policy

BASE = {"minimum_margin_pct": 15.0, "max_auto_discount_pct": 20.0}


def _policy(**overrides) -> PricingPolicy:
    return PricingPolicy(**{**BASE, **overrides})


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


# --- the real file ---------------------------------------------------------


def test_real_policy_file_loads_and_type_checks():
    policy = load_policy(POLICY_PATH)
    assert isinstance(policy, PricingPolicy)
    assert 0 <= policy.minimum_margin_pct <= 100
    assert policy.volume_discounts and policy.term_discounts and policy.segments


def test_real_policy_covers_every_customer_category_in_the_data():
    policy = load_policy(POLICY_PATH)
    covered = {s.customer_category for s in policy.segments}
    assert {"Retail Chain", "Reseller"} <= covered


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_policy(tmp_path / "does_not_exist.yaml")


# --- validation -------------------------------------------------------------


def test_out_of_range_margin_raises(tmp_path: Path):
    with pytest.raises(ValidationError):
        load_policy(_write(tmp_path, {**BASE, "minimum_margin_pct": 150}))


def test_unknown_legacy_field_is_ignored(tmp_path: Path):
    # large_order_threshold was dropped in favour of the volume ladder; an old
    # file that still carries it must not fail to load.
    policy = load_policy(_write(tmp_path, {**BASE, "large_order_threshold": 100}))
    assert policy.minimum_margin_pct == 15.0


@pytest.mark.parametrize(
    "tiers",
    [
        [{"min_quantity": 100, "discount_pct": 3}, {"min_quantity": 50, "discount_pct": 6}],  # thresholds fall
        [{"min_quantity": 50, "discount_pct": 6}, {"min_quantity": 100, "discount_pct": 3}],  # discounts fall
        [{"min_quantity": 50, "discount_pct": 3}, {"min_quantity": 50, "discount_pct": 6}],  # duplicate threshold
    ],
)
def test_volume_ladder_must_strictly_increase(tiers):
    with pytest.raises(ValidationError):
        _policy(volume_discounts=tiers)


def test_term_ladder_must_strictly_increase():
    with pytest.raises(ValidationError):
        _policy(
            term_discounts=[
                {"min_contract_months": 24, "discount_pct": 2},
                {"min_contract_months": 12, "discount_pct": 4},
            ]
        )


def test_duplicate_segment_raises():
    row = {"customer_category": "Reseller", "min_margin_pct": 18, "max_auto_discount_pct": 10}
    with pytest.raises(ValidationError):
        _policy(segments=[row, row])


# --- ladder lookups ---------------------------------------------------------


LADDER_POLICY = _policy(
    volume_discounts=[
        {"min_quantity": 50, "discount_pct": 3},
        {"min_quantity": 100, "discount_pct": 6},
        {"min_quantity": 250, "discount_pct": 10},
    ],
    term_discounts=[
        {"min_contract_months": 12, "discount_pct": 2},
        {"min_contract_months": 24, "discount_pct": 4},
    ],
)


@pytest.mark.parametrize(
    "quantity, expected",
    [(1, 0.0), (49, 0.0), (50, 3.0), (99, 3.0), (100, 6.0), (249, 6.0), (250, 10.0), (10_000, 10.0)],
)
def test_volume_discount_picks_highest_tier_met(quantity, expected):
    assert LADDER_POLICY.volume_discount_for(quantity) == expected


@pytest.mark.parametrize(
    "months, expected",
    [(None, 0.0), (0, 0.0), (6, 0.0), (12, 2.0), (23, 2.0), (24, 4.0), (60, 4.0)],
)
def test_term_discount_picks_highest_tier_met(months, expected):
    assert LADDER_POLICY.term_discount_for(months) == expected


def test_empty_ladders_give_zero_discount():
    assert _policy().volume_discount_for(1_000) == 0.0
    assert _policy().term_discount_for(36) == 0.0


# --- segment lookup ---------------------------------------------------------


SEGMENT_POLICY = _policy(
    segments=[
        {
            "customer_category": "Retail Chain",
            "customer_tier": "strategic",
            "min_margin_pct": 12,
            "max_auto_discount_pct": 20,
        },
        {"customer_category": "Retail Chain", "min_margin_pct": 15, "max_auto_discount_pct": 15},
        {"customer_category": "Reseller", "min_margin_pct": 18, "max_auto_discount_pct": 10},
    ]
)


def test_category_and_tier_match_beats_category_only():
    g = SEGMENT_POLICY.guardrails_for("Retail Chain", "strategic")
    assert (g.min_margin_pct, g.max_auto_discount_pct) == (12, 20)


def test_category_only_row_covers_other_tiers():
    g = SEGMENT_POLICY.guardrails_for("Retail Chain", "preferred")
    assert (g.min_margin_pct, g.max_auto_discount_pct) == (15, 15)


def test_category_without_tier_rows_uses_its_row():
    g = SEGMENT_POLICY.guardrails_for("Reseller", "standard")
    assert (g.min_margin_pct, g.max_auto_discount_pct) == (18, 10)


def test_unknown_category_falls_back_to_policy_defaults():
    g = SEGMENT_POLICY.guardrails_for("Wholesale", "standard")
    assert isinstance(g, SegmentGuardrails)
    assert g.min_margin_pct == SEGMENT_POLICY.minimum_margin_pct
    assert g.max_auto_discount_pct == SEGMENT_POLICY.max_auto_discount_pct


def test_segment_order_in_file_does_not_matter():
    reversed_policy = _policy(segments=list(reversed(SEGMENT_POLICY.model_dump()["segments"])))
    assert reversed_policy.guardrails_for("Retail Chain", "strategic").min_margin_pct == 12
    assert reversed_policy.guardrails_for("Retail Chain", "preferred").min_margin_pct == 15

"""Check hand-calculated workflow expectations; never generate expected values from the app."""

from __future__ import annotations

import json
from math import isclose
from pathlib import Path

from quote_workflow.contracts.case import QuoteCase


def load_golden(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in cases]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("golden cases must have unique ids and cannot be empty")
    return cases


def compare_case(case: QuoteCase, expected: dict) -> list[str]:
    """Return explicit mismatches; amount tolerance only absorbs binary float noise."""
    failures: list[str] = []

    def equal(label: str, actual: object, want: object) -> None:
        if actual != want:
            failures.append(f"{label}: expected {want!r}, got {actual!r}")

    def amount(label: str, actual: float | None, want: float | None) -> None:
        if actual is None or want is None:
            equal(label, actual, want)
        elif not isclose(actual, want, rel_tol=0, abs_tol=0.00001):
            failures.append(f"{label}: expected {want!r}, got {actual!r}")

    equal("case_status", case.status.value, expected["case_status"])
    pricing = case.pricing
    equal("pricing_status", pricing.status.value if pricing else None, expected["pricing_status"])
    amount("total", pricing.total_quoted_value if pricing else None, expected["total"])
    actual_lines = pricing.lines if pricing else []
    wanted_lines = expected["lines"]
    equal("line_count", len(actual_lines), len(wanted_lines))
    for i, (line, want) in enumerate(zip(actual_lines, wanted_lines, strict=False), start=1):
        equal(f"line {i} status", line.status.value, want["status"])
        amount(f"line {i} unit_price", line.final_unit_price, want["unit_price"])
        if "counter_price" in want:
            amount(f"line {i} counter_price", line.counter_unit_price, want["counter_price"])
    for phrase in expected.get("warning_contains", []):
        if not pricing or not any(phrase in warning for warning in pricing.warnings):
            failures.append(f"missing pricing warning containing {phrase!r}")
    for phrase in expected.get("missing_contains", []):
        if case.request is None or not any(phrase in field for field in case.request.missing_fields()):
            failures.append(f"missing request issue containing {phrase!r}")
    return failures

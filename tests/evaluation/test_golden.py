"""Check the golden runner and verify it detects a materially wrong expectation."""

from __future__ import annotations

import json

from quote_workflow.evaluation.golden import load_golden
from scripts.run_eval import GOLDEN_PATH, run


def test_golden_cases_pass() -> None:
    total, failures = run()
    assert total == 8
    assert failures == 0


def test_wrong_expected_price_fails(tmp_path) -> None:
    golden = load_golden(GOLDEN_PATH)
    golden[0]["total"] = 290.00
    path = tmp_path / "incorrect.json"
    path.write_text(json.dumps(golden), encoding="utf-8")
    _, failures = run(path)
    assert failures == 1

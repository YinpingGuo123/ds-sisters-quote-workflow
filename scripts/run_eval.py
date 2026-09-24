"""Run fixed-date, offline golden evaluations against a temporary catalog and case store.

Usage: python scripts/run_eval.py [--golden data/eval/golden_cases.json]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from quote_workflow.catalog.build import build_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.config import REPO_ROOT
from quote_workflow.evaluation.golden import compare_case, load_golden
from quote_workflow.samples import load_samples, sample_request
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import create_case_from_request

GOLDEN_PATH = REPO_ROOT / "data" / "eval" / "golden_cases.json"
AS_OF_DATE = date(2026, 9, 24)  # Deals in the fixture catalog depend on the date.


def run(golden_path: Path = GOLDEN_PATH) -> tuple[int, int]:
    expected = load_golden(golden_path)
    samples = {sample["id"]: sample for sample in load_samples()}
    failures = 0
    with TemporaryDirectory() as directory:
        root = Path(directory)
        catalog_path = root / "catalog.db"
        build_database(db_path=catalog_path)
        conn = get_connection(db_path=catalog_path)
        store = SqliteCaseStore(db_path=root / "cases.db")
        try:
            for target in expected:
                name = target["id"]
                if name not in samples:
                    problems = [f"no sample request found for {name!r}"]
                else:
                    try:
                        request = sample_request(samples[name], conn)
                        case = create_case_from_request(
                            store, conn, request, case_id=f"EVAL-{name}", as_of_date=AS_OF_DATE, use_llm=False
                        )
                        problems = compare_case(case, target)
                    except Exception as exc:
                        problems = [f"evaluation raised {type(exc).__name__}: {exc}"]
                print(f"{'FAIL' if problems else 'PASS'} {name}")
                for problem in problems:
                    print(f"  - {problem}")
                failures += bool(problems)
        finally:
            store.close()
            conn.close()
    print(f"{len(expected) - failures}/{len(expected)} golden cases passed")
    return len(expected), failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    args = parser.parse_args()
    _, failures = run(args.golden)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()

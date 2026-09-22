"""Create demo cases from data/samples/requests.json and run them through the
workflow. Idempotent: a sample whose case id already exists is skipped.

Usage:
    python scripts/seed_cases.py            # deterministic fallback summary
    python scripts/seed_cases.py --llm      # also call the LLM for the reviewer summary
"""

from __future__ import annotations

import argparse

from quote_workflow.catalog.build import ensure_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.samples import load_samples, sample_request
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import create_case_from_request


def seed(store: SqliteCaseStore, conn, use_llm: bool = False) -> list[str]:
    """Seed every sample not already present; returns the case ids created."""
    created: list[str] = []
    existing = {case.case_id for case in store.list()}
    for sample in load_samples():
        case_id = f"Q-{sample['id']}"
        if case_id in existing:
            continue
        case = create_case_from_request(store, conn, sample_request(sample, conn), case_id=case_id, use_llm=use_llm)
        created.append(case.case_id)
        print(f"{case.case_id:32} {case.status.value:18} {sample['title']}")
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--llm", action="store_true", help="call the LLM for the reviewer summary (needs OPENAI_API_KEY)"
    )
    args = parser.parse_args()

    ensure_database()
    conn = get_connection()
    store = SqliteCaseStore()
    created = seed(store, conn, use_llm=args.llm)
    print(f"{len(created)} case(s) created; {store.count()} in store")


if __name__ == "__main__":
    main()

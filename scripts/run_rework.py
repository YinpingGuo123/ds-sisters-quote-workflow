"""Find cases waiting for rework and carry it out.

This is the out-of-process half of the rework flow: a component that is not
the portal discovers work by asking the store for a status, does it, and
writes the result back through the same seam the portal uses. No queue, no
worker, no message bus - the case row is the work item.

Usage:
    python scripts/run_rework.py                 # list what is waiting
    python scripts/run_rework.py --run [--llm]   # run every open rework
    python scripts/run_rework.py Q-1024 --run
"""

from __future__ import annotations

import argparse

from quote_workflow.catalog.build import ensure_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import run_rework


def _line(case: QuoteCase) -> str:
    rework = case.rework
    target = rework.target.value if rework else "-"
    reason = rework.reason if rework else ""
    return f"{case.case_id:28} {target:10} {case.customer_display:22} {reason}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_id", nargs="?", help="only this case; default is every waiting case")
    parser.add_argument("--run", action="store_true", help="carry the rework out instead of just listing it")
    parser.add_argument("--llm", action="store_true", help="allow the LLM for the regenerated reviewer summary")
    args = parser.parse_args()

    store = SqliteCaseStore()
    waiting = store.list(status=CaseStatus.REWORK_REQUESTED)  # the whole discovery mechanism
    if args.case_id:
        waiting = [case for case in waiting if case.case_id == args.case_id]

    if not waiting:
        print("No case is waiting for rework.")
        return
    for case in waiting:
        print(_line(case))
    if not args.run:
        print(f"\n{len(waiting)} case(s) waiting. Re-run with --run to carry the rework out.")
        return

    ensure_database()
    conn = get_connection()
    print()
    for case in waiting:
        reworked = run_rework(store, conn, case.case_id, use_llm=args.llm)
        print(f"{reworked.case_id:28} -> {reworked.status.value} ({reworked.events[-1].message})")


if __name__ == "__main__":
    main()

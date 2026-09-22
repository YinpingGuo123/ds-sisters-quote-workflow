"""Print a case, or re-run the pipeline for one/all cases.

Usage:
    python scripts/run_case.py --all              # list every case with status and total
    python scripts/run_case.py Q-standard-quote   # show one case in detail
    python scripts/run_case.py Q-standard-quote --rerun [--llm]
"""

from __future__ import annotations

import argparse

from quote_workflow.catalog.build import ensure_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.contracts.case import QuoteCase
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import rerun


def _line(case: QuoteCase) -> str:
    total = f"${case.total_quoted_value:,.2f}" if case.total_quoted_value is not None else "-"
    pricing = case.pricing.status.value if case.pricing else "-"
    return f"{case.case_id:28} {case.status.value:18} {pricing:22} {total:>12}  {case.customer_display}"


def _show(case: QuoteCase) -> None:
    print(_line(case))
    if case.request:
        print(f"  missing: {case.request.missing_fields() or 'nothing'}")
        for n, line in enumerate(case.request.lines, start=1):
            print(f"  line {n}: {line.product_name} x {line.quantity} [{line.product_status.value}]")
    if case.pricing:
        for line in case.pricing.lines:
            print(
                f"  priced {line.line_number}: {line.product_name} "
                f"final ${line.final_unit_price:.2f} ({line.status.value})"
            )
            for sentence in line.rationale:
                print(f"      - {sentence}")
        for warning in case.pricing.warnings:
            print(f"  ! {warning}")
    if case.summary:
        print(f"  summary [{case.summary.generated_by}]: {case.summary.summary}")
    if case.quotation:
        print(
            f"  quotation {case.quotation.quote_number}: total ${case.quotation.total:,.2f}, "
            f"valid until {case.quotation.valid_until}"
        )
    print("  events:")
    for event in case.events:
        arrow = f" {event.from_status.value} -> {event.to_status.value}" if event.to_status else ""
        print(f"    {event.at:%H:%M:%S} [{event.stage}]{arrow}: {event.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()

    store = SqliteCaseStore()
    if args.all:
        for case in store.list():
            print(_line(case))
        return
    if not args.case_id:
        parser.error("give a case id or --all")
    if args.rerun:
        ensure_database()
        rerun(store, get_connection(), args.case_id, use_llm=args.llm)
    _show(store.get(args.case_id))


if __name__ == "__main__":
    main()

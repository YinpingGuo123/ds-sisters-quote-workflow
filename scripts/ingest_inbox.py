"""Ingest RFQ emails into cases.db.

Polls ``agenttesting986@gmail.com`` when ``INTAKE_IMAP_PASSWORD`` is set;
otherwise reads ``data/samples/inbox/*.txt``. Creates one QuoteCase per new
email (deduped by ``source_id``).

Usage:
    python scripts/build_db.py
    python scripts/ingest_inbox.py
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)  # .env wins over a stale shell OPENAI_API_KEY
except ImportError:
    pass

from quote_workflow.catalog.build import ensure_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.config import intake_imap_enabled, intake_mailbox_address
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.intake import fetch_new_rfqs, run_intake
from quote_workflow.intake.mailbox import mailbox_label
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import ingest_sources


def main() -> None:
    print(mailbox_label())
    if not intake_imap_enabled():
        print(f"  Tip: set INTAKE_IMAP_PASSWORD in .env to poll {intake_mailbox_address()}")
    ensure_database()
    conn = get_connection()
    store = SqliteCaseStore()
    created = ingest_sources(store, conn, fetch_new_rfqs(), run_intake, use_llm=False)
    for case in created:
        origin = case.source.source_id if case.source else "?"
        print(f"{case.case_id:12} {case.status.value:18} {origin}")
    print(f"{len(created)} new case(s); {store.count()} total in store")
    failed = [c.case_id for c in created if c.status == CaseStatus.FAILED]
    if failed:
        raise SystemExit(f"intake failed for: {', '.join(failed)}")


if __name__ == "__main__":
    main()

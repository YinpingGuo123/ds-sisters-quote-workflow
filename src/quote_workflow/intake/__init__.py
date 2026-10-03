"""Email intake: ``RfqSource`` -> ``QuoteRequest``.

Exposes ``fetch_new_rfqs()`` and ``run_intake(source, conn)`` for the workflow
and portal. Must not price, persist, or set case status.
"""

from __future__ import annotations

import sqlite3

from quote_workflow.catalog.resolution import resolve
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.source import RfqSource
from quote_workflow.intake.extract import extract_from_source, to_quote_request
from quote_workflow.intake.mailbox import fetch_new_rfqs, mailbox_label


def run_intake(source: RfqSource, conn: sqlite3.Connection) -> QuoteRequest:
    """Read one RFQ, extract fields, resolve names against the catalog."""
    extracted = extract_from_source(source)
    request = to_quote_request(extracted, source.body_text)
    return resolve(conn, request)


__all__ = ["fetch_new_rfqs", "mailbox_label", "run_intake"]

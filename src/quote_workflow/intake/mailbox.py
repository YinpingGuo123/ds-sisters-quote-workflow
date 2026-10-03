"""Read RFQs from the company Gmail inbox or from ``data/samples/inbox/*.txt``.

When ``INTAKE_IMAP_PASSWORD`` is set, ``fetch_new_rfqs`` polls
``agenttesting986@gmail.com`` (see ``config/intake.yaml``). Otherwise the
sample ``*.txt`` files are used for local demo and CI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from quote_workflow.config import INBOX_DIR, intake_imap_enabled, intake_mailbox_address
from quote_workflow.contracts.source import RfqSource
from quote_workflow.intake.gmail import fetch_from_gmail

# Fixed timestamp so sample ``fetch_new_rfqs`` is deterministic in tests.
_INBOX_EPOCH = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _parse_email_text(text: str) -> tuple[str | None, str]:
    text = text.strip()
    if text.lower().startswith("subject:"):
        newline = text.find("\n")
        subject_line = text if newline < 0 else text[:newline]
        subject = subject_line.split(":", 1)[1].strip() or None
        body = text[newline + 1 :].strip() if newline >= 0 else ""
        return subject, body
    return None, text


def fetch_sample_rfqs(inbox_dir: Path = INBOX_DIR) -> list[RfqSource]:
    """Every ``*.txt`` RFQ in the sample inbox directory, sorted by file name."""
    sources: list[RfqSource] = []
    for index, path in enumerate(sorted(inbox_dir.glob("*.txt"))):
        raw = path.read_text(encoding="utf-8")
        subject, body = _parse_email_text(raw)
        sources.append(
            RfqSource(
                source_id=path.name,
                received_at=_INBOX_EPOCH.replace(minute=index),
                sender=None,
                subject=subject,
                body_text=body,
            )
        )
    return sources


def fetch_new_rfqs(inbox_dir: Path = INBOX_DIR) -> list[RfqSource]:
    """New RFQs from the live mailbox when IMAP is configured, else sample files."""
    if intake_imap_enabled():
        return fetch_from_gmail()
    return fetch_sample_rfqs(inbox_dir)


def mailbox_label() -> str:
    """Human-readable description of the active mailbox source."""
    address = intake_mailbox_address()
    if intake_imap_enabled():
        return f"Live Gmail inbox: {address}"
    return f"RFQ address: {address} (sample files until INTAKE_IMAP_PASSWORD is set)"

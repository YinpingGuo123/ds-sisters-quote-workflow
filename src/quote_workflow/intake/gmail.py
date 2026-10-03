"""Pull RFQ emails from the company Gmail inbox over IMAP.

Configured in ``config/intake.yaml`` (address) and ``INTAKE_IMAP_PASSWORD``
(Gmail App Password in ``.env``). Uses stdlib ``imaplib`` only.
"""

from __future__ import annotations

import email
import imaplib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from quote_workflow.config import (
    intake_imap_folder,
    intake_imap_host,
    intake_imap_password,
    intake_imap_port,
    intake_mailbox_address,
)
from quote_workflow.contracts.source import RfqSource


def _decode_payload(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                text = _decode_payload(part).strip()
                if text:
                    return text
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/html":
                text = _decode_payload(part).strip()
                if text:
                    return text
        return ""
    return _decode_payload(msg).strip()


def _attachment_names(msg: email.message.Message) -> list[str]:
    names: list[str] = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            name = part.get_filename()
            if name:
                names.append(name)
    return names


def _source_id(msg: email.message.Message, uid: bytes) -> str:
    message_id = (msg.get("Message-ID") or "").strip().strip("<>")
    if message_id:
        return f"gmail-{message_id}"
    return f"gmail-uid-{uid.decode()}"


def _received_at(msg: email.message.Message) -> datetime:
    raw = msg.get("Date")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            pass
    return datetime.now(UTC)


def fetch_from_gmail() -> list[RfqSource]:
    """Every message in the configured IMAP folder, oldest first."""
    password = intake_imap_password()
    if not password:
        raise RuntimeError("INTAKE_IMAP_PASSWORD is not set")

    mailbox = intake_mailbox_address()
    conn = imaplib.IMAP4_SSL(intake_imap_host(), intake_imap_port())
    try:
        conn.login(mailbox, password)
        status, _ = conn.select(intake_imap_folder(), readonly=True)
        if status != "OK":
            raise RuntimeError(f"could not open folder {intake_imap_folder()!r}")

        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        uids = data[0].split()
        sources: list[RfqSource] = []
        for uid in uids:
            status, fetched = conn.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not fetched or fetched[0] is None:
                continue
            raw = fetched[0][1]
            if not isinstance(raw, bytes):
                continue
            msg = email.message_from_bytes(raw)
            body = _extract_body(msg)
            if not body:
                continue
            sources.append(
                RfqSource(
                    source_id=_source_id(msg, uid),
                    received_at=_received_at(msg),
                    sender=msg.get("From"),
                    subject=msg.get("Subject"),
                    body_text=body,
                    attachment_names=_attachment_names(msg),
                )
            )
        sources.sort(key=lambda source: source.received_at)
        return sources
    finally:
        try:
            conn.logout()
        except Exception:
            pass

"""Gmail IMAP intake with a fake IMAP connection."""

from __future__ import annotations

import email
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest

from quote_workflow.intake.gmail import fetch_from_gmail


def _sample_message() -> bytes:
    msg = email.message.EmailMessage()
    msg["From"] = "Customer <buyer@example.com>"
    msg["To"] = "agenttesting986@gmail.com"
    msg["Subject"] = "Quote for 10 launchers"
    msg["Message-ID"] = "<test-msg-001@example.com>"
    msg["Date"] = format_datetime(datetime(2026, 9, 30, 9, 0, 0, tzinfo=UTC))
    msg.set_content("Hi, please quote 10 USB missile launchers for Tailspin HQ.")
    return msg.as_bytes()


class FakeImap:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.logged_out = False

    def login(self, user: str, password: str) -> tuple[str, list]:
        assert user == "agenttesting986@gmail.com"
        assert password == "app-password"
        return "OK", [b"Logged in"]

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list]:
        assert folder == "INBOX"
        return "OK", [b"1"]

    def uid(self, command: str, *args):
        if command == "search":
            return "OK", [b"1001"]
        if command == "fetch":
            return "OK", [(b"1001 (RFC822)", _sample_message())]
        raise AssertionError(command)

    def logout(self) -> tuple[str, list]:
        self.logged_out = True
        return "OK", [b"bye"]


def test_fetch_from_gmail_parses_messages(monkeypatch):
    monkeypatch.setenv("INTAKE_IMAP_PASSWORD", "app-password")
    monkeypatch.setattr("quote_workflow.intake.gmail.imaplib.IMAP4_SSL", FakeImap)
    from quote_workflow.config import _intake_config

    _intake_config.cache_clear()

    sources = fetch_from_gmail()
    assert len(sources) == 1
    assert sources[0].source_id == "gmail-test-msg-001@example.com"
    assert sources[0].sender == "Customer <buyer@example.com>"
    assert "launchers" in sources[0].body_text


def test_fetch_from_gmail_requires_password(monkeypatch):
    monkeypatch.delenv("INTAKE_IMAP_PASSWORD", raising=False)
    from quote_workflow.config import _intake_config

    _intake_config.cache_clear()
    with pytest.raises(RuntimeError, match="INTAKE_IMAP_PASSWORD"):
        fetch_from_gmail()

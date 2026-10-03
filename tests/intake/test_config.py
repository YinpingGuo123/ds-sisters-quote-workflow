"""Intake mailbox configuration."""

from __future__ import annotations

from quote_workflow.config import intake_mailbox_address
from quote_workflow.intake.mailbox import mailbox_label


def test_company_mailbox_address_is_in_repo_config():
    assert intake_mailbox_address() == "agenttesting986@gmail.com"
    assert "agenttesting986@gmail.com" in mailbox_label()

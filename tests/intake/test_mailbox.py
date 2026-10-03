"""Inbox file reading: stable ids and subject/body parsing."""

from __future__ import annotations

from quote_workflow.intake.mailbox import fetch_new_rfqs


def test_fetch_new_rfqs_returns_stable_ids():
    first = fetch_new_rfqs()
    second = fetch_new_rfqs()
    assert first
    assert [s.source_id for s in first] == [s.source_id for s in second]
    assert all(s.source_id.endswith(".txt") for s in first)


def test_subject_is_parsed_from_sample_files():
    by_id = {source.source_id: source for source in fetch_new_rfqs()}
    assert by_id["discount-within-policy.txt"].subject == "Quote request"
    assert "Tailspin Toys" in by_id["discount-within-policy.txt"].body_text

from __future__ import annotations

import sqlite3

from quote_workflow.catalog.resolution import resolve
from quote_workflow.contracts.enums import ResolutionStatus
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest


def _single(customer_name, product_name, quantity) -> QuoteRequest:
    """One-line request, the way the old structured form built them."""
    line = QuoteLine(product_name=product_name, quantity=quantity if quantity and quantity > 0 else None)
    return QuoteRequest(customer_name=customer_name, lines=[line])


def test_exact_names_resolve_to_ids_and_canonical_names(built_db: sqlite3.Connection):
    request = _single("  tailspin toys (head office)", "usb missile launcher (green)", 20)
    resolved = resolve(built_db, request)
    assert resolved.customer_id == 1
    assert resolved.customer_name == "Tailspin Toys (Head Office)"
    assert resolved.customer_status == ResolutionStatus.RESOLVED
    assert resolved.lines[0].product_id == 1
    assert resolved.lines[0].product_name == "USB missile launcher (Green)"
    assert resolved.is_priceable


def test_aliases_resolve(built_db: sqlite3.Connection):
    resolved = resolve(built_db, _single("WT Retail", "launchers", 5))
    assert resolved.customer_id == 5
    assert resolved.lines[0].product_id == 1


def test_unique_token_match_resolves(built_db: sqlite3.Connection):
    resolved = resolve(built_db, _single("Tailspin Bow Mar", "the launchers for our stores", 5))
    assert resolved.customer_id == 2
    assert resolved.lines[0].product_id == 1
    assert resolved.lines[0].product_name == "USB missile launcher (Green)"


def test_several_matches_are_ambiguous_with_candidates_not_guessed(built_db: sqlite3.Connection):
    resolved = resolve(built_db, _single("Wingtip stores", "monster truck", 5))
    assert resolved.customer_status == ResolutionStatus.AMBIGUOUS
    assert resolved.customer_id is None
    assert len(resolved.customer_candidates) == 3
    assert resolved.lines[0].product_status == ResolutionStatus.AMBIGUOUS
    assert resolved.lines[0].product_id is None
    assert resolved.lines[0].candidates == [
        "RC big wheel monster truck with remote control (Black) 1/50 scale",
        "Ride on big wheel monster truck (Black) 1/12 scale",
    ]
    assert resolved.resolution_issues()[0].startswith("customer 'Wingtip stores' is ambiguous:")


def test_partial_match_is_a_did_you_mean_not_a_resolution(built_db: sqlite3.Connection):
    resolved = resolve(built_db, _single("Eric Torres", "some stuff for the office", 5))
    line = resolved.lines[0]
    assert line.product_status == ResolutionStatus.AMBIGUOUS and line.product_id is None
    assert line.candidates == ["Office cube periscope (Black)"]


def test_unknown_names_are_not_found(built_db: sqlite3.Connection):
    resolved = resolve(built_db, _single("Zeta Holdings", "Deluxe Rocket Backpack", 5))
    assert resolved.customer_status == ResolutionStatus.NOT_FOUND and resolved.customer_candidates == []
    assert resolved.lines[0].product_status == ResolutionStatus.NOT_FOUND and resolved.lines[0].candidates == []
    assert resolved.resolution_issues() == [
        "customer 'Zeta Holdings' not found",
        "line 1: product 'Deluxe Rocket Backpack' not found",
    ]


def test_missing_names_stay_missing(built_db: sqlite3.Connection):
    resolved = resolve(built_db, _single(None, None, None))
    assert resolved.customer_status == ResolutionStatus.MISSING
    assert resolved.lines[0].product_status == ResolutionStatus.MISSING


def test_each_line_is_resolved_independently(built_db: sqlite3.Connection):
    request = QuoteRequest(
        customer_name="Eric Torres",
        lines=[
            QuoteLine(product_name="periscope", quantity=10),
            QuoteLine(product_name="Nonexistent Widget", quantity=1),
            QuoteLine(product_name="Pack of 12 action figures (variety)"),
        ],
    )
    resolved = resolve(built_db, request)
    statuses = [line.product_status for line in resolved.lines]
    assert statuses == [ResolutionStatus.RESOLVED, ResolutionStatus.NOT_FOUND, ResolutionStatus.RESOLVED]
    assert [line.is_priceable for line in resolved.lines] == [True, False, False]
    assert not resolved.is_priceable


def test_already_resolved_ids_are_left_alone(built_db: sqlite3.Connection):
    # A UI selector can hand over ids directly; resolution must not second-guess them.
    request = QuoteRequest(
        customer_name="picked from a dropdown",
        customer_id=3,
        customer_status=ResolutionStatus.RESOLVED,
        lines=[QuoteLine(product_name="dropdown", product_id=9, product_status=ResolutionStatus.RESOLVED, quantity=1)],
    )
    resolved = resolve(built_db, request)
    assert (resolved.customer_id, resolved.lines[0].product_id) == (3, 9)
    assert resolved.customer_name == "picked from a dropdown"


def test_resolution_does_not_mutate_its_input(built_db: sqlite3.Connection):
    request = _single("Eric Torres", "periscope", 10)
    resolve(built_db, request)
    assert request.customer_id is None
    assert request.lines[0].product_status == ResolutionStatus.MISSING

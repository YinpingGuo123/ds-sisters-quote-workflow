from __future__ import annotations

import pytest
from pydantic import ValidationError

from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import ResolutionStatus
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest


def test_blank_request_is_honest_about_what_is_missing():
    request = QuoteRequest()
    assert request.customer_status == ResolutionStatus.MISSING
    assert request.lines == []
    assert not request.is_priceable
    assert request.resolution_issues() == ["customer not specified", "no products specified"]


@pytest.mark.parametrize("bad_quantity", [0, -1, -100])
def test_non_positive_quantity_raises(bad_quantity):
    with pytest.raises(ValidationError):
        QuoteLine(quantity=bad_quantity)


@pytest.mark.parametrize("field", ["requested_unit_price", "competitor_price"])
def test_non_positive_prices_raise(field):
    with pytest.raises(ValidationError):
        QuoteLine(**{field: 0})


def test_requested_discount_pct_bounds():
    assert QuoteRequest(requested_discount_pct=0).requested_discount_pct == 0
    assert QuoteRequest(requested_discount_pct=100).requested_discount_pct == 100
    with pytest.raises(ValidationError):
        QuoteRequest(requested_discount_pct=101)


def test_lists_are_independent_per_instance():
    a = QuoteRequest()
    b = QuoteRequest()
    a.lines.append(QuoteLine())
    assert b.lines == []


def test_is_priceable_requires_everything_resolved():
    resolved_line = QuoteLine(product_name="P", product_id=1, product_status=ResolutionStatus.RESOLVED, quantity=2)
    request = QuoteRequest(
        customer_name="C", customer_id=1, customer_status=ResolutionStatus.RESOLVED, lines=[resolved_line]
    )
    assert request.is_priceable

    no_qty = resolved_line.model_copy(update={"quantity": None})
    assert not request.model_copy(update={"lines": [resolved_line, no_qty]}).is_priceable
    assert not request.model_copy(update={"customer_status": ResolutionStatus.NOT_FOUND}).is_priceable


def test_issues_are_numbered_per_line_and_name_the_candidates():
    request = QuoteRequest(
        customer_name="Tailspin",
        customer_status=ResolutionStatus.AMBIGUOUS,
        customer_candidates=["Tailspin Toys (Head Office)", "Tailspin Toys (Avenal, CA)"],
        lines=[
            QuoteLine(product_name="launcher", product_id=1, product_status=ResolutionStatus.RESOLVED, quantity=10),
            QuoteLine(
                product_name="the mugs", product_status=ResolutionStatus.AMBIGUOUS, candidates=["DBA mug", "Dev mug"]
            ),
            QuoteLine(product_name="Gizmo", product_status=ResolutionStatus.NOT_FOUND, quantity=1),
        ],
    )
    assert request.resolution_issues() == [
        "customer 'Tailspin' is ambiguous: Tailspin Toys (Head Office), Tailspin Toys (Avenal, CA)",
        "line 2: product 'the mugs' is ambiguous: DBA mug, Dev mug",
        "line 2: quantity missing",
        "line 3: product 'Gizmo' not found",
    ]


def _address() -> Address:
    return Address(line1="1 Main St", city="Springfield", country="US")


def test_missing_fields_adds_addresses_on_top_of_resolution_issues():
    request = QuoteRequest(
        customer_name="Acme",
        customer_id=1,
        customer_status=ResolutionStatus.RESOLVED,
        lines=[QuoteLine(product_name="Widget", product_id=1, product_status=ResolutionStatus.RESOLVED, quantity=5)],
    )
    assert request.is_priceable
    assert request.missing_fields() == ["billing address missing", "shipping address missing"]
    assert not request.is_complete

    complete = request.model_copy(update={"billing_address": _address(), "shipping_address": _address()})
    assert complete.missing_fields() == []
    assert complete.is_complete


def test_address_as_text_skips_empty_parts():
    text = Address(
        name="Acme Co", line1="1 Main St", city="Springfield", region="IL", postal_code="62701", country="US"
    ).as_text()
    assert text == "Acme Co\n1 Main St\nSpringfield IL 62701\nUS"
    assert _address().as_text() == "1 Main St\nSpringfield\nUS"

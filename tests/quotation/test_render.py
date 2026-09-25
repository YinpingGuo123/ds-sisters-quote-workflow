from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import CaseStatus, PricingStatus, QuotationFormat
from quote_workflow.contracts.pricing import LineDecision, PricingDecision
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.quotation import RENDERERS, Renderer, build_quotation, renderer_for

NOW = datetime(2026, 9, 21, tzinfo=UTC)
BILL = Address(name="Acme HQ", line1="1 Main St", city="Springfield", region="IL", postal_code="62701", country="US")
SHIP = Address(name="Acme Warehouse", line1="9 Dock Rd", city="Peoria", region="IL", postal_code="61602", country="US")


def _line(number: int, name: str, qty: int, list_price: float, final: float) -> LineDecision:
    return LineDecision(
        line_number=number,
        product_id=number,
        product_name=name,
        quantity=qty,
        status=PricingStatus.APPROVED,
        status_reason="no_request",
        list_price=list_price,
        price_floor=list_price * 0.7,
        min_margin_pct=15.0,
        max_auto_discount_pct=20.0,
        applicable_deal=None,
        deal_kind=None,
        volume_discount_pct=0.0,
        term_discount_pct=0.0,
        recommended_unit_price=final,
        requested_unit_price=None,
        counter_unit_price=None,
        final_unit_price=final,
        line_total=qty * final,
        discount_pct=(list_price - final) / list_price * 100,
        margin_pct=30.0,
    )


def _case(with_addresses: bool = True) -> QuoteCase:
    lines = [_line(1, "Widget", 10, 30.0, 27.0), _line(2, "Gadget", 2, 100.0, 100.0)]
    pricing = PricingDecision(
        status=PricingStatus.APPROVED,
        lines=lines,
        total_list_value=500.0,
        total_quoted_value=470.0,
        total_discount_pct=6.0,
        blended_margin_pct=30.0,
        as_of_date=date(2026, 9, 21),
        policy_version="t",
        priced_at=NOW,
    )
    request = QuoteRequest(
        customer_name="Acme",
        billing_address=BILL if with_addresses else None,
        shipping_address=SHIP if with_addresses else None,
        requested_delivery_date=date(2026, 10, 15),
    )
    return QuoteCase(
        case_id="Q-1",
        status=CaseStatus.READY_FOR_REVIEW,
        created_at=NOW,
        updated_at=NOW,
        request=request,
        pricing=pricing,
    )


def test_quotation_copies_prices_and_renders_both_addresses():
    quotation = build_quotation(_case(), today=date(2026, 9, 21))
    assert quotation.quote_number == "Q-2026-Q-1"
    assert quotation.valid_until == date(2026, 10, 21)
    assert [line.line_total for line in quotation.lines] == [270.0, 200.0]
    assert quotation.subtotal == 500.0 and quotation.total == 470.0 and quotation.discount_amount == 30.0
    assert quotation.body_format is QuotationFormat.MARKDOWN
    body = quotation.body
    assert "# Quotation Q-2026-Q-1" in body
    assert "Acme HQ<br>1 Main St" in body and "Acme Warehouse<br>9 Dock Rd" in body
    assert "| 1 | Widget | 10 | $27.00 | $270.00 |" in body
    assert "**Requested delivery date:** 2026-10-15" in body
    assert "Discount | -$30.00" in body and "**Total** | **$470.00**" in body


def test_markdown_is_the_only_renderer_built_and_is_the_default():
    assert set(RENDERERS) == {QuotationFormat.MARKDOWN}
    markdown = renderer_for(QuotationFormat.MARKDOWN)
    assert (markdown.media_type, markdown.extension) == ("text/markdown", "md")


def test_another_format_plugs_in_without_changing_build_quotation():
    """The seam: a new format is a Renderer, not an edit to build_quotation."""
    html = Renderer(
        format=QuotationFormat.HTML,
        media_type="text/html",
        extension="html",
        render=lambda q: f"<h1>Quotation {q.quote_number}</h1><p>{q.total:.2f}</p>",
    )

    quotation = build_quotation(_case(), today=date(2026, 9, 21), renderer=html)

    assert quotation.body_format is QuotationFormat.HTML
    assert quotation.body == "<h1>Quotation Q-2026-Q-1</h1><p>470.00</p>"
    assert html.filename(quotation) == "Q-2026-Q-1.html"
    # the structured model is unchanged and still carries the prices pricing decided
    assert quotation.total == 470.0 and [line.line_total for line in quotation.lines] == [270.0, 200.0]


def test_quotation_requires_addresses_and_priced_lines():
    with pytest.raises(ValueError):
        build_quotation(_case(with_addresses=False))
    empty = _case()
    empty.pricing = empty.pricing.model_copy(update={"lines": []})
    with pytest.raises(ValueError):
        build_quotation(empty)

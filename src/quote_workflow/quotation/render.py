"""Build the Quotation for a case: a structured model plus an archival
rendering of it. Every price is copied from the PricingDecision.

This module names no document format. It takes a ``Renderer`` (defaulting to
markdown) and stores what that renderer produced, so adding HTML or PDF never
touches this file, ``workflow`` or the contracts.

Quote numbering and validity are simple conventions (``Q-<year>-<case id>``,
30 days).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.quotation import Quotation, QuotationLine
from quote_workflow.quotation.renderers import DEFAULT, Renderer

VALIDITY_DAYS = 30
PAYMENT_TERMS = "Net 30 days"
ESTIMATED_DELIVERY_NOTE = "Standard lead time is 2-3 weeks from order confirmation."


def build_quotation(case: QuoteCase, today: date | None = None, renderer: Renderer = DEFAULT) -> Quotation:
    """The quotation for a case. Requires a complete request and a pricing decision.

    Used both for the reviewer's draft preview and, on approval, for the
    quotation stored on the case - the same document either way.
    """
    if case.request is None or case.pricing is None:
        raise ValueError("a quotation needs a request and a pricing decision")
    if case.request.billing_address is None or case.request.shipping_address is None:
        raise ValueError("a quotation needs billing and shipping addresses")
    if not case.pricing.lines:
        raise ValueError("a quotation needs at least one priced line")

    today = today or date.today()
    lines = [
        QuotationLine(
            product_name=line.product_name,
            quantity=line.quantity,
            unit_price=line.final_unit_price,
            line_total=line.line_total,
        )
        for line in case.pricing.lines
    ]
    subtotal = case.pricing.total_list_value
    total = case.pricing.total_quoted_value
    discount = round(subtotal - total, 2)

    quotation = Quotation(
        quote_number=f"Q-{today.year}-{case.case_id}",
        case_id=case.case_id,
        quote_date=today,
        valid_until=today + timedelta(days=VALIDITY_DAYS),
        customer_name=case.request.customer_name or "",
        billing_address=case.request.billing_address,
        shipping_address=case.request.shipping_address,
        requested_delivery_date=case.request.requested_delivery_date,
        estimated_delivery_note=ESTIMATED_DELIVERY_NOTE,
        lines=lines,
        subtotal=subtotal,
        discount_amount=discount if discount > 0 else None,
        total=total,
        payment_terms=PAYMENT_TERMS,
        notes=case.review.comment if case.review and case.review.comment else None,
        body="",
        body_format=renderer.format,
        generated_at=datetime.now(UTC),
    )
    quotation.body = renderer.render(quotation)
    return quotation

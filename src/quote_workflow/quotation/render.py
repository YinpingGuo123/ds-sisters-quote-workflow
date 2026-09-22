"""Build the Quotation for an approved case: a structured model plus a
rendered markdown body. Every price is copied from the PricingDecision.

Quote numbering and validity are simple conventions (``Q-<year>-<case id>``,
30 days); PDF or HTML output would be another renderer over the same model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.quotation import Quotation, QuotationLine

VALIDITY_DAYS = 30
PAYMENT_TERMS = "Net 30 days"
ESTIMATED_DELIVERY_NOTE = "Standard lead time is 2-3 weeks from order confirmation."


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _cell(text: str) -> str:
    """Multi-line text inside a markdown table cell."""
    return text.replace("\n", "<br>")


def render_markdown(q: Quotation) -> str:
    rows = [
        "| # | Product | Qty | Unit price | Line total |",
        "|---|---|---:|---:|---:|",
        *(
            f"| {i} | {line.product_name} | {line.quantity} | {_money(line.unit_price)} | {_money(line.line_total)} |"
            for i, line in enumerate(q.lines, start=1)
        ),
    ]
    totals = [f"| | | | **Subtotal (list)** | {_money(q.subtotal)} |"]
    if q.discount_amount:
        totals.append(f"| | | | Discount | -{_money(q.discount_amount)} |")
    totals.append(f"| | | | **Total** | **{_money(q.total)}** |")

    delivery = (
        f"**Requested delivery date:** {q.requested_delivery_date.isoformat()}  " if q.requested_delivery_date else ""
    )
    parts = [
        f"# Quotation {q.quote_number}",
        "",
        f"**Quote date:** {q.quote_date.isoformat()}  ",
        f"**Valid until:** {q.valid_until.isoformat()}  ",
        f"**Case:** {q.case_id}",
        "",
        f"**Customer:** {q.customer_name}",
        "",
        "| Bill to | Ship to |",
        "|---|---|",
        f"| {_cell(q.billing_address.as_text())} | {_cell(q.shipping_address.as_text())} |",
        "",
        *([delivery] if delivery else []),
        *([f"**Delivery:** {q.estimated_delivery_note}"] if q.estimated_delivery_note else []),
        "",
        *rows,
        *totals,
        "",
        *([f"**Payment terms:** {q.payment_terms}"] if q.payment_terms else []),
        *([f"**Notes:** {q.notes}"] if q.notes else []),
    ]
    return "\n".join(parts).strip() + "\n"


def build_quotation(case: QuoteCase, today: date | None = None) -> Quotation:
    """The quotation for an approved case. Requires a complete request and a pricing decision."""
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
        body_markdown="",
        generated_at=datetime.now(UTC),
    )
    quotation.body_markdown = render_markdown(quotation)
    return quotation

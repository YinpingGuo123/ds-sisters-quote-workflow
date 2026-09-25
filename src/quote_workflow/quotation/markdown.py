"""The markdown renderer: Quotation -> markdown text.

One of possibly several renderers over the same model (see ``renderers.py``).
It reads the quotation and nothing else - no pricing, no case, no store - so
every number it prints was already decided by ``pricing``.
"""

from __future__ import annotations

from quote_workflow.contracts.quotation import Quotation


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _cell(text: str) -> str:
    """Multi-line text inside a markdown table cell."""
    return text.replace("\n", "<br>")


def render(q: Quotation) -> str:
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

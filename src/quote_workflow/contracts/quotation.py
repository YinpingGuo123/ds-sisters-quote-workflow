"""The quotation produced when a reviewer approves a case.

Structured model first; ``body_markdown`` is the rendered representation the
portal shows and offers for download. Any other renderer (PDF, HTML) is a
function over this model, added later if wanted.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from quote_workflow.contracts.common import Address


class QuotationLine(BaseModel):
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class Quotation(BaseModel):
    quote_number: str
    case_id: str
    quote_date: date
    valid_until: date

    customer_name: str
    billing_address: Address
    shipping_address: Address
    requested_delivery_date: date | None = None
    estimated_delivery_note: str | None = None  # static/demo text, e.g. "Typically ships in 2-3 weeks"

    lines: list[QuotationLine] = Field(default_factory=list)
    subtotal: float  # at list price
    discount_amount: float | None = None  # subtotal - total, when there is one
    total: float

    payment_terms: str | None = None
    notes: str | None = None

    body_markdown: str
    generated_at: datetime

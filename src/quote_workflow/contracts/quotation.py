"""The quotation produced when a reviewer approves a case.

The structured model is the source of truth and is format-neutral - no markup
anywhere in it. ``body`` is an archival snapshot of how it was rendered when
the reviewer approved it, and ``body_format`` says which renderer produced
that snapshot, so a later change to a renderer cannot rewrite what was sent.

Rendering itself lives in ``quotation.renderers``: a renderer is a function
over this model, and adding HTML or PDF adds one there without changing this
model, ``workflow`` or the portal.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import QuotationFormat


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

    body: str  # archival snapshot of the rendered document
    body_format: QuotationFormat = QuotationFormat.MARKDOWN
    generated_at: datetime

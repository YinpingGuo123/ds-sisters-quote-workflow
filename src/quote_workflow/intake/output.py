"""Structured-output schema for the RFQ extraction call.

Only the fields the model writes. ``extract`` maps them into the shared
``QuoteRequest`` and adds ``source_text`` from the email body.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, NonNegativeInt, PositiveFloat, PositiveInt


class LlmAddress(BaseModel):
    name: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None


class LlmLine(BaseModel):
    product_name: str
    quantity: PositiveInt | None = None
    requested_unit_price: PositiveFloat | None = None
    competitor_price: PositiveFloat | None = None


class LlmExtractedRfq(BaseModel):
    customer_name: str | None = None
    billing_address: LlmAddress | None = None
    shipping_address: LlmAddress | None = None
    requested_delivery_date: date | None = None
    contract_months: NonNegativeInt | None = None
    requested_discount_pct: float | None = Field(default=None, ge=0, le=100)
    lines: list[LlmLine] = Field(default_factory=list)
    notes: str | None = None
    clarification_questions: list[str] = Field(default_factory=list)

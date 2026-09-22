"""The normalized commercial request that pricing consumes.

A QuoteRequest is produced by intake (from an email, an attachment, customer
master data, a clarification reply - downstream never asks which) or built
directly from a structured sample. It must be able to represent a partial
request honestly, which is why every business field is Optional and why
resolution outcomes (``customer_status``, ``QuoteLine.product_status``) are
explicit fields rather than inferred from whether an id happens to be set.

``missing_fields()`` is the single, shared definition of "complete enough to
price and quote"; ``workflow.submit_request`` uses it to decide between
NEEDS_INFO and pricing, and intake can use it to know what to ask for.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, NonNegativeInt, PositiveFloat, PositiveInt

from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import ResolutionStatus


class QuoteLine(BaseModel):
    product_name: str | None = None  # as given: an exact name, alias, or raw mention
    product_id: int | None = None  # set by resolution
    product_status: ResolutionStatus = ResolutionStatus.MISSING
    candidates: list[str] = Field(default_factory=list)  # product names, when AMBIGUOUS
    quantity: PositiveInt | None = None
    requested_unit_price: PositiveFloat | None = None
    competitor_price: PositiveFloat | None = None

    @property
    def is_priceable(self) -> bool:
        return self.product_status == ResolutionStatus.RESOLVED and self.quantity is not None


class QuoteRequest(BaseModel):
    customer_name: str | None = None
    customer_id: int | None = None
    customer_status: ResolutionStatus = ResolutionStatus.MISSING
    customer_candidates: list[str] = Field(default_factory=list)

    billing_address: Address | None = None
    shipping_address: Address | None = None
    requested_delivery_date: date | None = None

    contract_months: NonNegativeInt | None = None
    requested_discount_pct: float | None = Field(
        default=None, ge=0, le=100
    )  # applies to every line without its own price
    lines: list[QuoteLine] = Field(default_factory=list)

    source_text: str | None = None  # the raw email / RFQ text, when there was one
    notes: str | None = None  # anything intake wants to pass along (urgency, competitor context, ...)
    # Questions intake would ask the customer. Display only - never used for pricing.
    clarification_questions: list[str] = Field(default_factory=list)

    @property
    def is_priceable(self) -> bool:
        """Customer resolved and every line priceable - what pricing needs."""
        return (
            self.customer_status == ResolutionStatus.RESOLVED
            and bool(self.lines)
            and all(line.is_priceable for line in self.lines)
        )

    @property
    def is_complete(self) -> bool:
        """Priceable *and* quotable: also needs both addresses."""
        return not self.missing_fields()

    def resolution_issues(self) -> list[str]:
        """What stops this request from being priced (identity + quantity problems)."""
        found: list[str] = []
        if self.customer_status == ResolutionStatus.MISSING:
            found.append("customer not specified")
        elif self.customer_status == ResolutionStatus.NOT_FOUND:
            found.append(f"customer '{self.customer_name}' not found")
        elif self.customer_status == ResolutionStatus.AMBIGUOUS:
            found.append(f"customer '{self.customer_name}' is ambiguous: {', '.join(self.customer_candidates)}")

        if not self.lines:
            found.append("no products specified")
        for number, line in enumerate(self.lines, start=1):
            if line.product_status == ResolutionStatus.MISSING:
                found.append(f"line {number}: product not specified")
            elif line.product_status == ResolutionStatus.NOT_FOUND:
                found.append(f"line {number}: product '{line.product_name}' not found")
            elif line.product_status == ResolutionStatus.AMBIGUOUS:
                found.append(f"line {number}: product '{line.product_name}' is ambiguous: {', '.join(line.candidates)}")
            if line.quantity is None:
                found.append(f"line {number}: quantity missing")
        return found

    def missing_fields(self) -> list[str]:
        """Everything that stops this request from being priced and quoted."""
        found = self.resolution_issues()
        if self.billing_address is None:
            found.append("billing address missing")
        if self.shipping_address is None:
            found.append("shipping address missing")
        return found

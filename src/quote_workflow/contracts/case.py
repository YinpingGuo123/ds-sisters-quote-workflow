"""The persisted case record.

A QuoteCase is the aggregate that flows through the system: what came in,
the normalized request, the pricing decision, the reviewer summary, the
human decision, the quotation, and the status. Feature modules never touch
it - they take typed inputs and return typed outputs, and ``workflow``
attaches those outputs here and persists the case through ``CaseStore``.

``events`` is the append-only history (``case_events`` table). The store
hydrates it on ``get`` and never reads it back from the JSON blob.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.contracts.pricing import PricingDecision
from quote_workflow.contracts.quotation import Quotation
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.review import ReviewDecision, ReviewerSummary
from quote_workflow.contracts.source import RfqSource

SCHEMA_VERSION = 1


class CaseEvent(BaseModel):
    at: datetime
    stage: str  # "intake" | "pricing" | "explain" | "review" | "quotation" | ...
    message: str
    level: Literal["info", "warning", "error"] = "info"
    from_status: CaseStatus | None = None
    to_status: CaseStatus | None = None


class QuoteCase(BaseModel):
    schema_version: int = SCHEMA_VERSION
    case_id: str
    status: CaseStatus
    created_at: datetime
    updated_at: datetime
    assigned_to: str | None = None

    source: RfqSource | None = None  # None when the case was created from a structured request
    request: QuoteRequest | None = None
    pricing: PricingDecision | None = None
    summary: ReviewerSummary | None = None
    review: ReviewDecision | None = None
    quotation: Quotation | None = None

    evaluation_ref: str | None = None  # id/URL of an evaluation record; its shape is evaluation's
    trace_id: str | None = None

    events: list[CaseEvent] = Field(default_factory=list, exclude=True)

    # --- display conveniences (no behavior) ---------------------------------

    @property
    def customer_display(self) -> str:
        if self.request and self.request.customer_name:
            return self.request.customer_name
        if self.source and self.source.sender:
            return self.source.sender
        return "-"

    @property
    def total_quoted_value(self) -> float | None:
        return self.pricing.total_quoted_value if self.pricing else None

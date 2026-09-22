"""What the reviewer reads (ReviewerSummary) and what the reviewer decides
(ReviewDecision).

``ReviewerSummary`` is the only LLM-authored content on a case. It is also the
structured-output schema for the ``explain`` call, so the model is forced into
exactly this shape, and it is validated against the pricing facts before it is
accepted. ``generated_by="fallback"`` marks a summary built in code because
the LLM was unavailable or its output failed validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from quote_workflow.contracts.enums import ReviewAction


class ReviewerSummary(BaseModel):
    summary: str  # 2-4 sentences: what the engine decided and why it matters commercially
    rationale: list[str] = Field(default_factory=list)  # rules / discounts / deals used, in the reviewer's language
    warnings: list[str] = Field(default_factory=list)  # risks, thin margins, expired deals the customer may expect
    attention_items: list[str] = Field(default_factory=list)  # what to look at before approving
    draft_reply: str | None = None  # customer-facing draft; must not leak cost, margin or internal vocabulary

    generated_by: Literal["llm", "fallback"] = "fallback"
    model: str | None = None
    rejected_reason: str | None = None  # why an LLM attempt was rejected (when generated_by == "fallback")


class ReviewDecision(BaseModel):
    action: ReviewAction
    reviewer: str
    comment: str | None = None
    decided_at: datetime

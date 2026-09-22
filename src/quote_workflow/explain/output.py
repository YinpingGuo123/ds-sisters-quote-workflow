"""The structured-output schema for the reviewer-summary call.

Only the fields the model writes. ``summarize`` copies them into the shared
``ReviewerSummary`` and adds provenance (``generated_by``, ``model``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LlmSummary(BaseModel):
    summary: str
    rationale: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    attention_items: list[str] = Field(default_factory=list)
    draft_reply: str | None = None

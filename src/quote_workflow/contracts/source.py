"""What came in: the raw RFQ as received, before intake reads it.

Deliberately minimal - enough for the portal's "Original RFQ" panel and for
intake to work from. What intake does with attachments is intake's choice.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RfqSource(BaseModel):
    source_id: str  # e.g. a mailbox message id or a sample file name
    received_at: datetime
    sender: str | None = None
    subject: str | None = None
    body_text: str
    attachment_names: list[str] = Field(default_factory=list)

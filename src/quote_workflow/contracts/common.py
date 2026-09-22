"""Small shared value types used by more than one contract."""

from __future__ import annotations

from pydantic import BaseModel


class Address(BaseModel):
    """A postal address as it appears on a quotation. Free-form enough for
    intake to fill from an email, an attachment, or customer master data."""

    name: str | None = None  # company / attention line
    line1: str
    line2: str | None = None
    city: str
    region: str | None = None  # state / province
    postal_code: str | None = None
    country: str

    def as_text(self) -> str:
        """One line per part, for rendering in the portal and the quotation."""
        locality = " ".join(part for part in (self.city, self.region, self.postal_code) if part)
        parts = [self.name, self.line1, self.line2, locality, self.country]
        return "\n".join(part for part in parts if part)

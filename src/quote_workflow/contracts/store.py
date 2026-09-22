"""The case persistence interface. ``storage`` implements it; ``workflow``,
the portal and evaluation depend on this Protocol, not on SQLite."""

from __future__ import annotations

from typing import Protocol

from quote_workflow.contracts.case import CaseEvent, QuoteCase
from quote_workflow.contracts.enums import CaseStatus


class CaseStore(Protocol):
    def create(self, case: QuoteCase, event: CaseEvent) -> QuoteCase:
        """Insert a new case and its first event. Returns the case with events hydrated."""
        ...

    def get(self, case_id: str) -> QuoteCase:
        """The case with its events. Raises KeyError when unknown."""
        ...

    def save(self, case: QuoteCase, event: CaseEvent | None = None) -> None:
        """Write the current state and, in the same transaction, append ``event`` if given."""
        ...

    def list(self, status: CaseStatus | None = None, assigned_to: str | None = None) -> list[QuoteCase]:
        """Cases newest-first, without events, optionally filtered."""
        ...

    def events(self, case_id: str) -> list[CaseEvent]:
        """The append-only history for one case, oldest first."""
        ...

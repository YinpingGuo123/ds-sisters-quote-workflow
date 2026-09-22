"""Shared status vocabulary.

All ``StrEnum`` so they serialize to plain strings in JSON, SQLite and traces.
"""

from __future__ import annotations

from enum import StrEnum


class CaseStatus(StrEnum):
    """Lifecycle of a QuoteCase. Transitions live in ``workflow.status``.

    ``READY_FOR_REVIEW`` means: the request is complete *and* a PricingDecision
    exists - that is the boundary a human reviewer sees.
    """

    RECEIVED = "received"
    NEEDS_INFO = "needs_info"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_INFO = "request_info"


class ResolutionStatus(StrEnum):
    """Whether a name on the request could be matched to a catalog record.

    Set by whoever resolves the request (intake, or the ``catalog.resolve``
    helper) - never guessed downstream.
    """

    RESOLVED = "resolved"
    MISSING = "missing"  # the field was not provided at all
    NOT_FOUND = "not_found"  # provided, but matches nothing
    AMBIGUOUS = "ambiguous"  # provided, matches several candidates


class PricingStatus(StrEnum):
    """Deterministic outcome of pricing one line, rolled up to the quote as
    the worst line status in the order listed here.

    ``ESCALATION_REQUIRED`` means a human may still say yes; ``COUNTER_RECOMMENDED``
    means the request breaks the margin floor, which nobody can approve, so a
    counter is the only useful answer. ``INSUFFICIENT_DATA`` means at least one
    part of the request could not be priced.
    """

    APPROVED = "approved"
    COUNTER_RECOMMENDED = "counter_recommended"
    ESCALATION_REQUIRED = "escalation_required"
    INSUFFICIENT_DATA = "insufficient_data"

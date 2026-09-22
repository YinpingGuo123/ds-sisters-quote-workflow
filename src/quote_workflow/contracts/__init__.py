"""Shared contracts: the only shapes modules exchange.

Only true cross-module models live here. Module-internal types (the pricing
engine's dataclasses, the catalog's row shapes) stay in their own modules.
New fields must be Optional with defaults so stored cases keep loading.
"""

from quote_workflow.contracts.case import SCHEMA_VERSION, CaseEvent, QuoteCase
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.enums import CaseStatus, PricingStatus, ResolutionStatus, ReviewAction
from quote_workflow.contracts.pricing import Lever, LineDecision, PricingDecision
from quote_workflow.contracts.quotation import Quotation, QuotationLine
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest
from quote_workflow.contracts.review import ReviewDecision, ReviewerSummary
from quote_workflow.contracts.source import RfqSource
from quote_workflow.contracts.store import CaseStore

__all__ = [
    "SCHEMA_VERSION",
    "Address",
    "CaseEvent",
    "CaseStatus",
    "CaseStore",
    "Lever",
    "LineDecision",
    "PricingDecision",
    "PricingStatus",
    "Quotation",
    "QuotationLine",
    "QuoteCase",
    "QuoteLine",
    "QuoteRequest",
    "ResolutionStatus",
    "ReviewAction",
    "ReviewDecision",
    "ReviewerSummary",
    "RfqSource",
]

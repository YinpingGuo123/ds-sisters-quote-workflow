"""DSister Quote Workflow: RFQ -> QuoteCase -> deterministic pricing ->
reviewer portal -> quotation.

Modules exchange the shapes in ``quote_workflow.contracts``; ``quote_workflow.workflow``
is the only module that composes the others. See CLAUDE.md and docs/architecture-review.md.
"""

__version__ = "0.1.0"

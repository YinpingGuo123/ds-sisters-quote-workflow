"""LLM reviewer summary over deterministic pricing facts: grounded, validated,
with a code-built fallback. Never changes a number."""

from quote_workflow.explain.fallback import fallback_summary
from quote_workflow.explain.summarize import summarize

__all__ = ["fallback_summary", "summarize"]

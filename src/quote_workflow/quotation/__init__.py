"""Quotation output: the structured Quotation model plus the renderers that
turn it into a document. ``build_quotation`` is format-agnostic; formats live
in ``renderers`` (markdown today, HTML/PDF by adding one entry there)."""

from quote_workflow.quotation.render import build_quotation
from quote_workflow.quotation.renderers import DEFAULT, RENDERERS, Renderer, renderer_for

__all__ = ["DEFAULT", "RENDERERS", "Renderer", "build_quotation", "renderer_for"]

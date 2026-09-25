"""Which document formats a Quotation can be rendered into.

A renderer is a function over the ``Quotation`` model plus the two facts a
caller needs to serve the result: a media type and a file extension. Nothing
else knows about formats - ``workflow`` builds quotations with the default
renderer, and the portal asks a renderer for its media type instead of
hardcoding one.

To add a format: write ``quotation/html.py`` with a ``render(q)`` function and
add one ``Renderer`` line to ``RENDERERS`` below. No base class, no
registration decorator, nothing to change in ``contracts`` or ``workflow``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from quote_workflow.contracts.enums import QuotationFormat
from quote_workflow.contracts.quotation import Quotation
from quote_workflow.quotation import markdown


class Renderer(NamedTuple):
    format: QuotationFormat
    media_type: str
    extension: str
    render: Callable[[Quotation], str | bytes]  # bytes once a PDF renderer exists

    def filename(self, quotation: Quotation) -> str:
        return f"{quotation.quote_number}.{self.extension}"


MARKDOWN = Renderer(QuotationFormat.MARKDOWN, "text/markdown", "md", markdown.render)

RENDERERS: dict[QuotationFormat, Renderer] = {MARKDOWN.format: MARKDOWN}
DEFAULT = MARKDOWN


def renderer_for(fmt: QuotationFormat) -> Renderer:
    """The renderer for a format. Raises KeyError for a format not built yet."""
    return RENDERERS[fmt]

"""Resolution helper: match the names on a QuoteRequest to catalog records.

Deterministic. Offered to intake (and used by the sample seeding path); intake
may resolve some other way as long as the ids it sets exist in the catalog.
Three rungs, in order:

1. exact name or business alias (``repository.find_*``) - resolved;
2. deterministic token search (``repository.search_*``): a *unique full* match
   ("launchers" -> the one product whose name contains "launcher") is
   resolved;
3. anything else - several full matches ("the mugs"), only partial matches
   ("green mug"), or nothing - is NOT resolved. Candidates are listed as
   AMBIGUOUS so a person can pick; no candidates means NOT_FOUND.

Whatever produced the request only needs to supply the mention text.
"""

from __future__ import annotations

import sqlite3

from quote_workflow.catalog.repository import search_customers, search_products
from quote_workflow.contracts.enums import ResolutionStatus
from quote_workflow.contracts.quote_request import QuoteLine, QuoteRequest


def _resolve_line(conn: sqlite3.Connection, line: QuoteLine) -> QuoteLine:
    if line.product_status == ResolutionStatus.RESOLVED and line.product_id is not None:
        return line  # already resolved (e.g. picked from a selector by id)
    if not line.product_name:
        return line.model_copy(
            update={"product_id": None, "product_status": ResolutionStatus.MISSING, "candidates": []}
        )

    hits = search_products(conn, line.product_name)
    if len(hits) == 1 and hits[0].full_match:
        product = hits[0].record
        return line.model_copy(
            update={
                "product_id": product.product_id,
                "product_name": product.product_name,  # canonical name replaces the alias/mention
                "product_status": ResolutionStatus.RESOLVED,
                "candidates": [],
            }
        )
    status = ResolutionStatus.AMBIGUOUS if hits else ResolutionStatus.NOT_FOUND
    return line.model_copy(
        update={"product_id": None, "product_status": status, "candidates": [h.record.product_name for h in hits]}
    )


def resolve(conn: sqlite3.Connection, request: QuoteRequest) -> QuoteRequest:
    """Return a copy with ids and resolution statuses filled in. Never raises."""
    update: dict = {}
    if request.customer_status == ResolutionStatus.RESOLVED and request.customer_id is not None:
        pass
    elif not request.customer_name:
        update.update(customer_id=None, customer_status=ResolutionStatus.MISSING, customer_candidates=[])
    else:
        hits = search_customers(conn, request.customer_name)
        if len(hits) == 1 and hits[0].full_match:
            customer = hits[0].record
            update.update(
                customer_id=customer.customer_id,
                customer_name=customer.customer_name,
                customer_status=ResolutionStatus.RESOLVED,
                customer_candidates=[],
            )
        else:
            update.update(
                customer_id=None,
                customer_status=ResolutionStatus.AMBIGUOUS if hits else ResolutionStatus.NOT_FOUND,
                customer_candidates=[h.record.customer_name for h in hits],
            )

    update["lines"] = [_resolve_line(conn, line) for line in request.lines]
    return request.model_copy(update=update)

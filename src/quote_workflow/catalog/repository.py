"""Read-only catalog lookups: customer/product by name, alias or id; deals;
sales history; deterministic token search for free-text mentions.

Each function takes an explicit ``sqlite3.Connection`` (see
``catalog.connection.get_connection``) rather than opening its own - trivially
testable against a temporary database, and the data dependency is visible at
the call site. No LLM logic lives here. Intake may expose ``search_*`` to an
LLM as tools; pricing uses ``get_*`` to fetch its inputs.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from quote_workflow.catalog.types import CustomerInfo, Deal, ProductInfo, SaleRecord


def _normalize(name: str) -> str:
    return name.strip().lower()


# Words that carry no identity ("the launchers for our stores" -> "launcher").
_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "for",
    "our",
    "your",
    "some",
    "and",
    "or",
    "in",
    "at",
    "to",
    "unit",
    "units",
    "pcs",
    "pieces",
    "piece",
    "each",
    "x",
    "please",
    "order",
    "stores",
    "store",
}


def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, stopwords dropped, naive singulars ("mugs" -> "mug")."""
    out = set()
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        if token in _STOPWORDS:
            continue
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        out.add(token)
    return out


class SearchHit:
    """One candidate from a token search: the record, and whether the query was fully covered."""

    __slots__ = ("record", "full_match", "score")

    def __init__(self, record, full_match: bool, score: int):
        self.record = record
        self.full_match = full_match
        self.score = score


def _token_search(query_tokens: set[str], haystacks: list[tuple[object, set[str]]], limit: int) -> list[SearchHit]:
    """Rank records by how many query tokens their text contains.

    Records covering *every* query token come first; if any exist, only those
    are returned (a full match is a different kind of evidence from a
    partial one). Otherwise partial matches are returned as candidates for a
    "did you mean...?" question. Ties are broken by id order for determinism.
    """
    hits = []
    for record, tokens in haystacks:
        score = len(query_tokens & tokens)
        if score:
            hits.append(SearchHit(record, full_match=score == len(query_tokens), score=score))
    full = [h for h in hits if h.full_match]
    chosen = full if full else hits
    chosen.sort(key=lambda h: -h.score)
    return chosen[:limit]


def _customer_from_row(row: sqlite3.Row) -> CustomerInfo:
    return CustomerInfo(
        customer_id=row["customer_id"],
        customer_name=row["customer_name"],
        customer_category=row["customer_category"],
        buying_group=row["buying_group"],
        customer_tier=row["customer_tier"],
    )


def _product_from_row(row: sqlite3.Row) -> ProductInfo:
    return ProductInfo(
        product_id=row["product_id"],
        product_name=row["product_name"],
        list_price=row["list_price"],
        cost_price=row["cost_price"],
        product_category=row["product_category"],
    )


def _deal_from_row(row: sqlite3.Row) -> Deal:
    return Deal(
        deal_id=row["deal_id"],
        customer_id=row["customer_id"],
        buying_group=row["buying_group"],
        customer_category=row["customer_category"],
        product_id=row["product_id"],
        min_quantity=row["min_quantity"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]),
        discount_pct=row["discount_pct"],
        fixed_unit_price=row["fixed_unit_price"],
    )


def _sale_from_row(row: sqlite3.Row) -> SaleRecord:
    return SaleRecord(
        customer_id=row["customer_id"],
        product_id=row["product_id"],
        sale_date=date.fromisoformat(row["sale_date"]),
        quantity=row["quantity"],
        unit_price=row["unit_price"],
    )


def get_customer(conn: sqlite3.Connection, customer_name: str) -> CustomerInfo | None:
    """Look up a customer by name (case/whitespace-insensitive exact match).

    No fuzzy matching: the spec requires never fabricating a customer, and a
    similarity match could silently resolve to the wrong one. Returns None
    when nothing matches.
    """
    target = _normalize(customer_name)
    result = None
    for row in conn.execute("SELECT * FROM customers"):
        if _normalize(row["customer_name"]) == target:
            result = _customer_from_row(row)
            break
    return result


def get_product(conn: sqlite3.Connection, product_name: str) -> ProductInfo | None:
    """Look up a product by name (case/whitespace-insensitive exact match)."""
    target = _normalize(product_name)
    result = None
    for row in conn.execute("SELECT * FROM products"):
        if _normalize(row["product_name"]) == target:
            result = _product_from_row(row)
            break
    return result


def get_customer_by_id(conn: sqlite3.Connection, customer_id: int) -> CustomerInfo | None:
    row = conn.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
    return _customer_from_row(row) if row is not None else None


def get_product_by_id(conn: sqlite3.Connection, product_id: int) -> ProductInfo | None:
    row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
    return _product_from_row(row) if row is not None else None


def find_customer(conn: sqlite3.Connection, text: str) -> CustomerInfo | None:
    """Resolve free text to a customer: exact name first, then the alias table.

    Still no fuzzy matching - an alias is business-defined shorthand, so
    resolving through it is as deliberate as an exact name.
    """
    result = get_customer(conn, text)
    if result is None:
        row = conn.execute("SELECT customer_id FROM customer_aliases WHERE alias = ?", (text.strip(),)).fetchone()
        if row is not None:
            result = get_customer_by_id(conn, row["customer_id"])
    return result


def find_product(conn: sqlite3.Connection, text: str) -> ProductInfo | None:
    """Resolve free text to a product: exact name first, then the alias table."""
    result = get_product(conn, text)
    if result is None:
        row = conn.execute("SELECT product_id FROM product_aliases WHERE alias = ?", (text.strip(),)).fetchone()
        if row is not None:
            result = get_product_by_id(conn, row["product_id"])
    return result


def _alias_tokens(conn: sqlite3.Connection, table: str, id_column: str) -> dict[int, set[str]]:
    by_id: dict[int, set[str]] = {}
    for row in conn.execute(f"SELECT alias, {id_column} FROM {table}"):
        by_id.setdefault(row[id_column], set()).update(_tokens(row["alias"]))
    return by_id


def search_customers(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[SearchHit]:
    """Candidates for a free-text customer mention, best first.

    An exact name/alias hit is returned alone. Otherwise a deterministic
    token match over names and aliases - the point is to *list* what the
    mention could mean, not to guess; ``catalog.resolution`` only accepts a
    unique full match.
    """
    exact = find_customer(conn, query)
    if exact is not None:
        result = [SearchHit(exact, full_match=True, score=1)]
    else:
        aliases = _alias_tokens(conn, "customer_aliases", "customer_id")
        haystacks = [
            (_customer_from_row(row), _tokens(row["customer_name"]) | aliases.get(row["customer_id"], set()))
            for row in conn.execute("SELECT * FROM customers ORDER BY customer_id")
        ]
        result = _token_search(_tokens(query), haystacks, limit)
    return result


def search_products(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[SearchHit]:
    """Candidates for a free-text product mention, best first (see search_customers)."""
    exact = find_product(conn, query)
    if exact is not None:
        result = [SearchHit(exact, full_match=True, score=1)]
    else:
        aliases = _alias_tokens(conn, "product_aliases", "product_id")
        haystacks = [
            (
                _product_from_row(row),
                _tokens(row["product_name"]) | _tokens(row["product_category"]) | aliases.get(row["product_id"], set()),
            )
            for row in conn.execute("SELECT * FROM products ORDER BY product_id")
        ]
        result = _token_search(_tokens(query), haystacks, limit)
    return result


def get_deals(conn: sqlite3.Connection) -> list[Deal]:
    """Every special deal, active or not.

    Filtering (scope, quantity threshold, validity window) is the engine's
    job - ``select_applicable_deal`` picks the one that applies, and expired
    deals that would otherwise have matched are surfaced as levers, which is
    why the engine needs to see them too.
    """
    return [_deal_from_row(row) for row in conn.execute("SELECT * FROM special_deals ORDER BY deal_id")]


_COUNTED_TABLES = ("customers", "products", "customer_aliases", "product_aliases", "special_deals", "sales_history")


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many reference records were built, per table.

    For the portal's monitoring view: it answers "is the catalog actually
    populated" without anything outside this module writing SQL.
    """
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _COUNTED_TABLES}


def get_sales_history(conn: sqlite3.Connection, customer_id: int, product_id: int) -> list[SaleRecord]:
    """Past transactions for the exact customer/product pair, most recent first."""
    rows = conn.execute(
        "SELECT * FROM sales_history WHERE customer_id = ? AND product_id = ? ORDER BY sale_date DESC",
        (customer_id, product_id),
    )
    result = [_sale_from_row(row) for row in rows]
    return result

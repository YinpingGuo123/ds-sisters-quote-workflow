"""Reference data: the SQLite catalog (customers, products, aliases, deals,
sales history), read-only lookups, and the deterministic ``resolve`` helper."""

from quote_workflow.catalog.build import build_database, ensure_database
from quote_workflow.catalog.connection import get_connection
from quote_workflow.catalog.repository import (
    SearchHit,
    find_customer,
    find_product,
    get_customer,
    get_customer_by_id,
    get_deals,
    get_product,
    get_product_by_id,
    get_sales_history,
    search_customers,
    search_products,
)
from quote_workflow.catalog.resolution import resolve
from quote_workflow.catalog.types import CustomerInfo, Deal, ProductInfo, SaleRecord

__all__ = [
    "CustomerInfo",
    "Deal",
    "ProductInfo",
    "SaleRecord",
    "SearchHit",
    "build_database",
    "ensure_database",
    "find_customer",
    "find_product",
    "get_connection",
    "get_customer",
    "get_customer_by_id",
    "get_deals",
    "get_product",
    "get_product_by_id",
    "get_sales_history",
    "resolve",
    "search_customers",
    "search_products",
]

"""Row shapes the catalog hands to the pricing engine.

Plain frozen dataclasses, decoupled from SQLite: the engine and its tests only
ever see these, never a ``sqlite3.Row``. ``repository.py`` adapts rows into them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CustomerInfo:
    customer_id: int
    customer_name: str
    customer_category: str
    buying_group: str | None
    customer_tier: str  # standard | preferred | strategic - see policy.yaml segments


@dataclass(frozen=True)
class ProductInfo:
    product_id: int
    product_name: str
    list_price: float
    cost_price: float
    product_category: str


@dataclass(frozen=True)
class Deal:
    deal_id: int
    customer_id: int | None
    buying_group: str | None
    customer_category: str | None
    product_id: int | None
    min_quantity: int | None
    start_date: date
    end_date: date
    discount_pct: float | None
    fixed_unit_price: float | None

    @property
    def is_contractual(self) -> bool:
        """Negotiated pricing (customer-specific or a fixed unit price) that the
        engine honors even below the margin floor - versus a *promotional*
        percentage deal (buying-group / category / unrestricted), which is
        clamped to the floor like any other discount.
        """
        return self.customer_id is not None or self.fixed_unit_price is not None


@dataclass(frozen=True)
class SaleRecord:
    customer_id: int
    product_id: int
    sale_date: date
    quantity: int
    unit_price: float

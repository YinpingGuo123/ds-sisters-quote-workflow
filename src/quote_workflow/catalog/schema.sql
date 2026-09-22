-- Reference-data (catalog) schema. Rebuilt from scratch every
-- time build_database() runs (drop-and-recreate, no migrations) - see
-- catalog.build for the rationale.

DROP TABLE IF EXISTS product_aliases;
DROP TABLE IF EXISTS customer_aliases;
DROP TABLE IF EXISTS special_deals;
DROP TABLE IF EXISTS sales_history;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id       INTEGER PRIMARY KEY,
    customer_name     TEXT NOT NULL UNIQUE,
    customer_category TEXT NOT NULL,
    buying_group      TEXT,
    credit_limit      REAL NOT NULL DEFAULT 0,
    -- Commercial tier used by config/policy.yaml's per-segment guardrails.
    customer_tier     TEXT NOT NULL CHECK (customer_tier IN ('standard', 'preferred', 'strategic'))
);

CREATE TABLE products (
    product_id       INTEGER PRIMARY KEY,
    product_name     TEXT NOT NULL UNIQUE,
    list_price       REAL NOT NULL,
    cost_price       REAL NOT NULL,
    product_category TEXT NOT NULL
);

-- Business-defined shorthand for email intake ("WT Retail" -> Wingtip HQ).
-- Deliberately small: anything a name match can already resolve, or that is
-- genuinely ambiguous ("monster truck" is two products), is left out.
CREATE TABLE customer_aliases (
    alias       TEXT PRIMARY KEY COLLATE NOCASE,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id)
);

CREATE TABLE product_aliases (
    alias      TEXT PRIMARY KEY COLLATE NOCASE,
    product_id INTEGER NOT NULL REFERENCES products(product_id)
);

CREATE TABLE sales_history (
    sale_id     INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    sale_date   TEXT NOT NULL,       -- ISO 8601 YYYY-MM-DD
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL
);

CREATE TABLE special_deals (
    deal_id           INTEGER PRIMARY KEY,
    customer_id       INTEGER REFERENCES customers(customer_id),
    buying_group      TEXT,
    customer_category TEXT,
    product_id        INTEGER REFERENCES products(product_id),
    min_quantity      INTEGER,
    start_date        TEXT NOT NULL,
    end_date          TEXT NOT NULL,
    discount_pct      REAL,
    fixed_unit_price  REAL,
    CHECK (discount_pct IS NOT NULL OR fixed_unit_price IS NOT NULL)
);

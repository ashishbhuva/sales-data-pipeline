-- Star schema for sales reporting (SQLite).
-- One fact table of order lines, joined to customer, product and date dimensions.

CREATE TABLE dim_customer (
    customer_id   TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    region        TEXT,
    industry      TEXT
);

CREATE TABLE dim_product (
    product_id   TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    list_price   REAL
);

CREATE TABLE dim_date (
    date_key  INTEGER PRIMARY KEY,   -- e.g. 20250307
    full_date TEXT NOT NULL,
    month     TEXT NOT NULL,         -- e.g. 2025-03
    fy        TEXT NOT NULL          -- Australian financial year, e.g. FY25
);

CREATE TABLE fact_sales (
    order_id    TEXT PRIMARY KEY,
    date_key    INTEGER NOT NULL REFERENCES dim_date(date_key),
    customer_id TEXT    NOT NULL REFERENCES dim_customer(customer_id),
    product_id  TEXT    NOT NULL REFERENCES dim_product(product_id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  REAL    NOT NULL CHECK (unit_price > 0),
    line_total  REAL    NOT NULL
);

-- Reporting view: monthly revenue by region, ready for Power BI or Excel
CREATE VIEW vw_monthly_region_sales AS
SELECT d.month,
       c.region,
       COUNT(*)                   AS order_lines,
       ROUND(SUM(f.line_total), 2) AS revenue
FROM fact_sales f
JOIN dim_date d     ON d.date_key = f.date_key
JOIN dim_customer c ON c.customer_id = f.customer_id
GROUP BY d.month, c.region;

"""ETL pipeline: raw CSV exports -> cleaned, validated data -> SQLite star schema.

Steps
  1. Extract   read the raw CSV files as text, so nothing is silently converted
  2. Transform standardise dates, money, regions and text; remove duplicates
  3. Validate  apply business rules; failing rows go to a quarantine file with a reason
  4. Load      rebuild a star schema (dimensions + fact table) in SQLite
  5. Report    write a data quality report

Run: python src/make_raw_data.py && python src/pipeline.py
"""
import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
DB_PATH = ROOT / "data" / "warehouse.db"
SCHEMA = ROOT / "sql" / "schema.sql"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

REGION_MAP = {
    "wa": "WA", "w.a.": "WA", "western australia": "WA",
    "qld": "QLD", "queensland": "QLD",
    "nsw": "NSW", "n.s.w": "NSW", "new south wales": "NSW",
    "nt": "NT", "northern territory": "NT",
}


# ---------- Extract ----------
def extract() -> dict:
    tables = {name: pd.read_csv(RAW / f"{name}.csv", dtype=str, keep_default_na=False)
              for name in ("orders", "customers", "products")}
    for name, df in tables.items():
        log.info("Extracted %s: %d rows", name, len(df))
    return tables


# ---------- Transform helpers (unit tested) ----------
def parse_date(value: str):
    """Parse ISO (2025-03-07), Australian (07/03/2025) or 07-Mar-2025 dates. Returns NaT if invalid."""
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"):
        parsed = pd.to_datetime(value, format=fmt, errors="coerce")
        if pd.notna(parsed):
            return parsed
    return pd.NaT


def parse_money(value) -> float:
    """Turn '$1,234.50' or '1234.5' into 1234.5. Returns NaN if it is not a number."""
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return float("nan")


def standardise_region(value: str):
    return REGION_MAP.get(str(value).strip().lower())


# ---------- Transform + validate ----------
def transform(tables: dict):
    customers = tables["customers"].copy()
    customers["customer_name"] = customers.customer_name.str.strip()
    customers["region"] = customers.region.map(standardise_region)
    customers["industry"] = customers.industry.str.strip().str.title()

    products = tables["products"].copy()
    products["list_price"] = products.list_price.map(parse_money)

    orders = tables["orders"].copy()
    before = len(orders)
    orders = orders.drop_duplicates()
    duplicates = before - len(orders)
    log.info("Removed %d duplicate rows", duplicates)

    orders["order_date"] = orders.order_date.map(parse_date)
    orders["quantity"] = pd.to_numeric(orders.quantity, errors="coerce")
    orders["unit_price"] = orders.unit_price.map(parse_money)
    orders["customer_id"] = orders.customer_id.str.strip()

    # Business rules: each failing row is quarantined with the first reason found
    rules = [
        ("missing customer_id", orders.customer_id.eq("")),
        ("unknown customer_id", ~orders.customer_id.isin(customers.customer_id) & orders.customer_id.ne("")),
        ("invalid order_date", orders.order_date.isna()),
        ("unknown product_id", ~orders.product_id.isin(products.product_id)),
        ("quantity must be positive", ~(orders.quantity > 0)),
        ("invalid unit_price", ~(orders.unit_price > 0)),
    ]
    orders["reject_reason"] = None
    for reason, failed in rules:
        orders.loc[failed & orders.reject_reason.isna(), "reject_reason"] = reason

    rejected = orders[orders.reject_reason.notna()]
    clean = orders[orders.reject_reason.isna()].drop(columns="reject_reason")
    clean["line_total"] = (clean.quantity * clean.unit_price).round(2)
    log.info("Validated orders: %d clean, %d rejected", len(clean), len(rejected))
    return customers, products, clean, rejected, duplicates


# ---------- Load ----------
def load(customers, products, orders) -> None:
    DB_PATH.unlink(missing_ok=True)  # full rebuild keeps every run repeatable
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA.read_text())

    dates = pd.DataFrame({"full_date": orders.order_date.drop_duplicates().sort_values()})
    dates["date_key"] = dates.full_date.dt.strftime("%Y%m%d").astype(int)
    dates["month"] = dates.full_date.dt.strftime("%Y-%m")
    dates["fy"] = "FY" + (dates.full_date.dt.year + (dates.full_date.dt.month >= 7)).astype(str).str[-2:]
    dates["full_date"] = dates.full_date.dt.strftime("%Y-%m-%d")

    customers[["customer_id", "customer_name", "region", "industry"]].to_sql(
        "dim_customer", con, if_exists="append", index=False)
    products[["product_id", "product_name", "list_price"]].to_sql(
        "dim_product", con, if_exists="append", index=False)
    dates[["date_key", "full_date", "month", "fy"]].to_sql("dim_date", con, if_exists="append", index=False)

    fact = orders.assign(date_key=orders.order_date.dt.strftime("%Y%m%d").astype(int))[
        ["order_id", "date_key", "customer_id", "product_id", "quantity", "unit_price", "line_total"]]
    fact.to_sql("fact_sales", con, if_exists="append", index=False)
    con.commit()
    log.info("Loaded %d fact rows into %s", len(fact), DB_PATH.name)
    con.close()


# ---------- Report ----------
def report(raw_rows: int, duplicates: int, clean, rejected) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(OUT / "quarantine_orders.csv", index=False)
    clean.to_csv(OUT / "clean_orders.csv", index=False)
    summary = {
        "raw_rows": raw_rows,
        "duplicates_removed": duplicates,
        "clean_rows": len(clean),
        "rejected_rows": len(rejected),
        "pass_rate_pct": round(100 * len(clean) / (raw_rows - duplicates), 1),
        "rejections_by_reason": rejected.reject_reason.value_counts().to_dict(),
        "clean_revenue_aud": round(float(clean.line_total.sum()), 2),
    }
    (OUT / "data_quality_report.json").write_text(json.dumps(summary, indent=2))
    log.info("Data quality report: %s", json.dumps(summary))
    return summary


def run() -> dict:
    tables = extract()
    customers, products, clean, rejected, duplicates = transform(tables)
    load(customers, products, clean)
    return report(len(tables["orders"]), duplicates, clean, rejected)


if __name__ == "__main__":
    run()

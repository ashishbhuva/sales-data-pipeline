"""Unit and end-to-end tests. Run with: pytest -q"""
import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import make_raw_data  # noqa: E402
import pipeline  # noqa: E402


def test_parse_date_handles_all_formats():
    assert pipeline.parse_date("2025-03-07") == pd.Timestamp("2025-03-07")
    assert pipeline.parse_date("07/03/2025") == pd.Timestamp("2025-03-07")  # day first (AU)
    assert pipeline.parse_date("07-Mar-2025") == pd.Timestamp("2025-03-07")


def test_parse_date_rejects_impossible_date():
    assert pd.isna(pipeline.parse_date("31/02/2025"))


def test_parse_money_strips_symbols():
    assert pipeline.parse_money("$1,234.50") == 1234.5
    assert pipeline.parse_money("9.9") == 9.9
    assert math.isnan(pipeline.parse_money("abc"))


def test_region_spellings_are_standardised():
    for raw in ["WA", " wa ", "W.A.", "Western Australia"]:
        assert pipeline.standardise_region(raw) == "WA"
    assert pipeline.standardise_region("Mars") is None


def test_end_to_end_pipeline():
    make_raw_data.main()
    summary = pipeline.run()

    # every non-duplicate row is either clean or quarantined, never lost
    assert summary["clean_rows"] + summary["rejected_rows"] == summary["raw_rows"] - summary["duplicates_removed"]
    assert summary["rejected_rows"] > 0

    con = sqlite3.connect(pipeline.DB_PATH)
    fact_rows = con.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
    orphans = con.execute(
        "SELECT COUNT(*) FROM fact_sales f LEFT JOIN dim_customer c USING (customer_id) WHERE c.customer_id IS NULL"
    ).fetchone()[0]
    bad_qty = con.execute("SELECT COUNT(*) FROM fact_sales WHERE quantity <= 0").fetchone()[0]
    con.close()

    assert fact_rows == summary["clean_rows"]
    assert orphans == 0
    assert bad_qty == 0

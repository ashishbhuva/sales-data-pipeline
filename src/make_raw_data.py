"""Create messy raw input files that look like real exports from different systems.

The data is simulated. Problems are added on purpose so the pipeline has
something real to clean: duplicate rows, mixed date formats, currency text,
inconsistent region names, stray spaces, missing IDs and impossible values.

Output: data/raw/orders.csv and data/raw/customers.csv
"""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED = 7
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

PRODUCTS = {
    "P100": ("Survey Stakes 900mm (bundle 50)", 4.50),
    "P200": ("Marking Paint Fluoro Pink 350g", 11.00),
    "P300": ("Safety Sign - Mine Site Entry", 38.00),
    "P400": ("Flagging Tape Orange 75m", 6.50),
    "P500": ("Steel Star Pegs 1.8m", 9.00),
}
# The same region written different ways, as happens across systems
REGION_SPELLINGS = {
    "WA": ["WA", "W.A.", "Western Australia", " wa "],
    "QLD": ["QLD", "Qld", "Queensland"],
    "NSW": ["NSW", "N.S.W", "New South Wales"],
    "NT": ["NT", "Northern Territory"],
}


def messy_date(d: date, rng: random.Random) -> str:
    style = rng.random()
    if style < 0.6:
        return d.isoformat()                 # 2025-03-07
    if style < 0.9:
        return d.strftime("%d/%m/%Y")        # 07/03/2025 (Australian)
    return d.strftime("%d-%b-%Y")            # 07-Mar-2025


def main() -> None:
    rng = random.Random(SEED)
    RAW.mkdir(parents=True, exist_ok=True)

    customers = []
    for i in range(1, 41):
        region = rng.choice(list(REGION_SPELLINGS))
        customers.append(
            {
                "customer_id": f"C{i:03d}",
                "customer_name": f"  Customer {i:03d} Pty Ltd ",
                "region": rng.choice(REGION_SPELLINGS[region]),
                "industry": rng.choice(["Mining", "mining", "Construction", "Surveying"]),
            }
        )
    pd.DataFrame(customers).to_csv(RAW / "customers.csv", index=False)

    orders = []
    start = date(2025, 7, 1)
    for n in range(1, 1501):
        d = start + timedelta(days=rng.randint(0, 364))
        pid = rng.choice(list(PRODUCTS))
        qty = rng.randint(1, 120)
        price = PRODUCTS[pid][1] * rng.uniform(0.95, 1.05)
        row = {
            "order_id": f"SO{200000 + n}",
            "order_date": messy_date(d, rng),
            "customer_id": f"C{rng.randint(1, 40):03d}",
            "product_id": pid,
            "quantity": qty,
            "unit_price": f"${price:,.2f}" if rng.random() < 0.3 else round(price, 2),
        }
        # Inject data quality problems (about 6% of rows)
        r = rng.random()
        if r < 0.015:
            row["customer_id"] = ""                 # missing customer
        elif r < 0.03:
            row["quantity"] = -row["quantity"]      # impossible quantity
        elif r < 0.04:
            row["order_date"] = "31/02/2025"        # invalid date
        elif r < 0.05:
            row["product_id"] = "P999"              # unknown product
        orders.append(row)
        if rng.random() < 0.03:                      # exact duplicate export rows
            orders.append(dict(row))

    pd.DataFrame(orders).to_csv(RAW / "orders.csv", index=False)
    pd.DataFrame(
        [{"product_id": k, "product_name": v[0], "list_price": v[1]} for k, v in PRODUCTS.items()]
    ).to_csv(RAW / "products.csv", index=False)
    print(f"Wrote {len(orders)} raw order rows, {len(customers)} customers, {len(PRODUCTS)} products to {RAW}")


if __name__ == "__main__":
    main()

"""Profile the raw tables to inform the star schema design."""

import duckdb
import pandas as pd

from src.config import DB_PATH

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

CHECKS = [
    (
        "Order statuses",
        "SELECT order_status, count(*) AS n FROM raw.orders GROUP BY 1 ORDER BY 2 DESC",
    ),
    (
        "Delivered-date coverage",
        "SELECT count(*) AS total_rows, count(order_delivered_customer_date) AS delivered FROM raw.orders",
    ),
    (
        "Customers vs people",
        "SELECT count(*) AS customer_rows, count(DISTINCT customer_unique_id) AS people FROM raw.customers",
    ),
    (
        "Order items fan-out",
        "SELECT count(*) AS item_rows, count(DISTINCT order_id) AS orders FROM raw.order_items",
    ),
    (
        "Geolocation duplicates",
        "SELECT count(*) AS geo_rows, count(DISTINCT geolocation_zip_code_prefix) AS zips FROM raw.geolocation",
    ),
]


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    for label, query in CHECKS:
        print(f"--- {label} ---")
        print(con.execute(query).fetchdf())
        print()

    con.close()


if __name__ == "__main__":
    main()
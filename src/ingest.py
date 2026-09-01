"""Load the raw Olist CSV files into DuckDB."""

import duckdb

from src.config import RAW_DATA_DIR, DB_DIR, DB_PATH, RAW_SCHEMA

TABLES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def main() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")

    for table_name, file_name in TABLES.items():
        csv_path = RAW_DATA_DIR / file_name

        if not csv_path.exists():
            raise FileNotFoundError(f"Missing CSV: {csv_path}")

        con.execute(
            f"""
            CREATE OR REPLACE TABLE {RAW_SCHEMA}.{table_name} AS
            SELECT * FROM read_csv_auto(?, sample_size = -1)
            """,
            [str(csv_path)],
        )

        row_count = con.execute(
            f"SELECT count(*) FROM {RAW_SCHEMA}.{table_name}"
        ).fetchone()[0]

        print(f"{table_name:<22} {row_count:>10,} rows")

    con.close()
    print(f"\nDatabase written to {DB_PATH}")


if __name__ == "__main__":
    main()
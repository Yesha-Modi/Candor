"""Quick look at what's in the database."""

import duckdb
import pandas as pd

from src.config import DB_PATH

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

con = duckdb.connect(str(DB_PATH), read_only=True)

print("--- Tables by schema ---")
print(
    con.execute(
        """
        select
            schema as schema_name,
            name   as table_name
        from (show all tables)
        order by schema, name
        """
    ).fetchdf()
)
print()

print("--- raw.orders, first 5 rows ---")
print(con.execute("SELECT * FROM raw.orders LIMIT 5").fetchdf())
print()

print("--- raw.orders columns ---")
print(con.execute("DESCRIBE raw.orders").fetchdf())

con.close()
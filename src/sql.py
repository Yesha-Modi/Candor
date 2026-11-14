"""Run one ad-hoc query against the database, read-only.

For the one-off checks that are not gold questions and not cross-checks: a
hunch to test, a number to confirm, a "wait, is that right?" at 10pm.

    python -m src.sql "select count(*) from marts.fct_orders"
    python -m src.sql --file checks/orders_with_hb.sql

The connection is read-only, so nothing typed here can change the database.
"""

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from src.config import DB_PATH

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 100)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default=None,
                        help="the SQL, in quotes")
    parser.add_argument("--file", default=None,
                        help="path to a .sql file to run instead")
    args = parser.parse_args()

    if args.file:
        sql = Path(args.file).read_text(encoding="utf-8")
    elif args.query:
        sql = args.query
    else:
        parser.error("give a query in quotes, or --file path/to/query.sql")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(sql).fetchdf()
    finally:
        con.close()

    if df.empty:
        print("(no rows)")
    else:
        print(df.to_string(index=False))
        print(f"\n{len(df)} row(s)")


if __name__ == "__main__":
    main()
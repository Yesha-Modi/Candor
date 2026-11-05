"""Print the columns and types of every table, grouped by schema."""

import duckdb

from src.config import DB_PATH

SCHEMAS = ["marts", "staging", "raw"]


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    for schema in SCHEMAS:
        tables = con.execute(
            """
            select distinct table_name
            from information_schema.columns
            where table_schema = ?
            order by table_name
            """,
            [schema],
        ).fetchall()

        if not tables:
            continue

        print(f"\n{'=' * 70}")
        print(f"  {schema.upper()}  —  {len(tables)} tables")
        print(f"{'=' * 70}")

        for (table,) in tables:
            columns = con.execute(
                """
                select column_name, data_type
                from information_schema.columns
                where table_schema = ? and table_name = ?
                order by ordinal_position
                """,
                [schema, table],
            ).fetchall()

            print(f"\n{schema}.{table}  ({len(columns)} columns)")
            for name, dtype in columns:
                print(f"    {name:<26} {dtype}")

    con.close()
    print()


if __name__ == "__main__":
    main()
"""Prove the guard rejects what it must and permits what it must.

    python -m eval.check_guard

Two lists, and the second one matters as much as the first. A guard that
rejects everything is trivially "safe" and useless, so every legitimate query
below must pass. This is the same rule as the gold questions: a check that
cannot fail is not a check.

Exits non-zero if any case is wrong, so it can gate a commit later.
"""

import sys

from agent.guard import allowed_tables_from_layer, validate_sql
from agent.prompt import load_layer

MUST_PASS = [
    ("plain count",
     "select count(*) from marts.fct_orders where is_delivered"),
    ("money with rounding",
     "select round(sum(item_price), 2) from marts.fct_order_items where is_delivered"),
    ("join and group",
     """select p.category, round(sum(i.item_price), 2) as item_revenue
        from marts.fct_order_items i
        join marts.dim_products p on i.product_key = p.product_key
        where i.is_delivered
        group by 1 order by 2 desc limit 5"""),
    ("cte then join",
     """with per_order as (
            select order_key, sum(item_price) as v
            from marts.fct_order_items group by 1
        )
        select count(*) from marts.fct_orders o
        join per_order p on o.order_key = p.order_key"""),
    ("correlated exists",
     """select count(*) from marts.fct_orders o
        where exists (select 1 from marts.fct_order_items i
                      where i.order_key = o.order_key)"""),
    ("set operation",
     "select 1 union all select 2"),
    ("window function",
     """select month, sum(x) over (order by month)
        from (select 1 as month, 2 as x)"""),
    # The false-positive cases: legitimate SQL that a text search would
    # reject. These are the reason the guard parses instead of grepping.
    ("alias contains 'drop'",
     "select count(*) as price_drop_orders from marts.fct_orders"),
    ("'drop' as a quoted identifier",
     'select count(*) as "drop" from marts.fct_orders'),
    ("'drop' inside a comment",
     "select count(*) /* drop */ from marts.fct_orders"),
    ("CTE named 'deleted_orders'",
     "with deleted_orders as (select 1 a) select a from deleted_orders"),
    ("dangerous text in a string literal",
     "select count(*) from marts.fct_orders where 'drop table' = 'x'"),
]

MUST_FAIL = [
    ("drop",                "drop table marts.fct_orders"),
    ("delete",              "delete from marts.fct_orders"),
    ("update",              "update marts.fct_orders set is_delivered = false"),
    ("insert",              "insert into marts.fct_orders values (1)"),
    ("create",              "create table evil as select 1"),
    ("two statements",      "select 1; drop table marts.fct_orders"),
    ("attach another db",   "attach 'evil.db' as evil"),
    ("copy to disk",        "copy marts.fct_orders to 'C:/out.csv'"),
    ("pragma",              "pragma database_list"),
    ("install extension",   "install httpfs"),
    ("load extension",      "load httpfs"),
    ("set a setting",       "set memory_limit='1GB'"),
    ("read a file in FROM", "select * from read_csv_auto('C:/Windows/win.ini')"),
    ("read a file, no FROM", "select read_csv_auto('C:/Windows/win.ini')"),
    ("list a directory",    "select * from glob('C:/*')"),
    ("read parquet",        "select * from read_parquet('x.pq')"),
    ("file via union",      "select 1 union all select * from read_csv('x')"),
    ("file via subquery",
     "select * from marts.fct_orders where order_key in (select * from read_csv('x'))"),
    ("undeclared table",    "select * from secret_table"),
    ("other schema",        "select * from main.users"),
    ("sql from json",       "select json_execute_serialized_sql('{}')"),
    ("csv as a table",      "select * from 'secret.csv'"),
    ("describe",            "describe marts.fct_orders"),
    ("empty",               ""),
    ("not sql",             "not sql at all"),
]


def main() -> None:
    allowed = allowed_tables_from_layer(load_layer())
    print(f"allowlist: {len(allowed)} tables from the semantic layer\n")

    wrong = 0

    print("MUST PASS")
    for label, sql in MUST_PASS:
        problems = validate_sql(sql, allowed)
        if problems:
            wrong += 1
            print(f"  WRONG  {label:<22} blocked: {problems[0]}")
        else:
            print(f"  ok     {label}")

    print("\nMUST FAIL")
    for label, sql in MUST_FAIL:
        problems = validate_sql(sql, allowed)
        if not problems:
            wrong += 1
            print(f"  WRONG  {label:<22} was allowed through")
        else:
            print(f"  ok     {label:<22} {problems[0]}")

    total = len(MUST_PASS) + len(MUST_FAIL)
    print(f"\n{total - wrong}/{total} correct")

    if wrong:
        print("The guard is not behaving as specified. Do not ship this.")
        sys.exit(1)


if __name__ == "__main__":
    main()
"""Verify gold answers automatically, by computing each one a second independent way.

Each check runs two queries that must agree. If they disagree, one of them is wrong —
and the point is that the two take different routes through the data, so a mistake in
one is unlikely to be repeated in the other.
"""

import duckdb

from src.config import DB_PATH

# Currency comparisons need cent precision; percentages need much finer,
# since 0.01 percentage points on ~96,000 rows is about 10 rows.
TOLERANCE = 0.0001

CHECKS = [
    {
        "for": "Q001",
        "name": "Order count survives the fact build",
        "a": "select count(*) from marts.fct_orders",
        "b": "select count(*) from staging.stg_orders",
    },
    {
        "for": "Q002",
        "name": "is_delivered matches the raw status",
        "a": "select count(*) from marts.fct_orders where is_delivered",
        "b": "select count(*) from staging.stg_orders where status = 'delivered'",
    },
    {
        "for": "Q003",
        "name": "Delivered revenue, from orders vs from items",
        "a": "select round(sum(order_value), 2) from marts.fct_orders where is_delivered",
        "b": """select round(sum(item_price) + sum(freight_price), 2)
                from marts.fct_order_items where is_delivered""",
    },
    {
        "for": "Q004",
        "name": "Average order value equals sum divided by count",
        "a": "select round(avg(order_value), 2) from marts.fct_orders where is_delivered",
        "b": """select round(sum(order_value) / count(*), 2)
                from marts.fct_orders where is_delivered""",
    },
    {
        "for": "Q005",
        "name": "Customer dimension is one row per person",
        "a": "select count(*) from marts.dim_customers",
        "b": "select count(distinct customer_unique_id) from staging.stg_customers",
    },
    {
        "for": "Q006",
        "name": "is_repeat_customer matches order_count > 1",
        "a": "select count(*) from marts.dim_customers where is_repeat_customer",
        "b": "select count(*) from marts.dim_customers where order_count > 1",
    },
    {
        "for": "Q007",
        "name": "Average review score, from the fact vs from staging",
        "a": """select round(avg(review_score), 3)
                from marts.fct_orders where review_count > 0""",
        "b": """with per_order as (
                    select order_id, avg(score) as s
                    from staging.stg_order_reviews group by order_id
                )
                select round(avg(s), 3) from per_order""",
    },
    {
        "for": "Q008",
        "name": "is_cancelled matches the two raw statuses",
        "a": "select count(*) from marts.fct_orders where is_cancelled",
        "b": """select count(*) from staging.stg_orders
                where status in ('canceled', 'unavailable')""",
    },
    {
        "for": "Q009",
        "name": "Delivery days, stored vs recomputed from timestamps",
        "a": """select round(avg(days_to_deliver), 4)
                from marts.fct_orders where days_to_deliver is not null""",
        "b": """select round(avg(date_diff('day', purchased_at, delivered_at)), 4)
                from staging.stg_orders where delivered_at is not null""",
    },
    {
        "for": "Q010",
        "name": "is_late matches a direct timestamp comparison",
        "a": "select count(*) from marts.fct_orders where is_late",
        "b": """select count(*) from staging.stg_orders
                where delivered_at is not null
                  and delivered_at > estimated_delivery_at""",
    },
    {
        "for": "Q011",
        "name": "Product dimension keeps every product",
        "a": "select count(*) from marts.dim_products",
        "b": "select count(*) from staging.stg_products",
    },
    {
        "for": "Q012",
        "name": "Seller dimension keeps every seller",
        "a": "select count(*) from marts.dim_sellers",
        "b": "select count(*) from staging.stg_sellers",
    },
    {
        "for": "Q013",
        "name": "Freight total, from orders vs from items",
        "a": "select round(sum(freight_value), 2) from marts.fct_orders where is_delivered",
        "b": """select round(sum(freight_price), 2)
                from marts.fct_order_items where is_delivered""",
    },
    {
        "for": "Q014",
        "name": "Late share equals late count over delivered-with-a-date",
        "a": """select round(100.0 * count(*) filter (where is_late) / count(*), 4)
                from marts.fct_orders
                where is_delivered and delivered_at is not null""",
        # Route b must apply the same is_delivered filter to the numerator.
        # Counting every late order, including the one that is not delivered,
        # makes the two routes disagree by a single row.
        "b": """select round(100.0
                    * (select count(*) from marts.fct_orders
                       where is_late and is_delivered)
                    / (select count(*) from marts.fct_orders
                       where is_delivered and delivered_at is not null), 4)""",
    },
    {
        "for": "Q015",
        "name": "Multi-item orders, from the flag vs counted from items",
        "a": "select count(*) from marts.fct_orders where item_count > 1",
        "b": """with per_order as (
                    select order_key, count(*) as n
                    from marts.fct_order_items group by order_key
                )
                select count(*) from per_order where n > 1""",
    },
    {
        "for": "Q016/Q029",
        "name": "Category revenue sums back to total delivered item revenue",
        "a": """select round(sum(item_price), 2)
                from marts.fct_order_items where is_delivered""",
        "b": """with by_category as (
                    select p.category, sum(i.item_price) as rev
                    from marts.fct_order_items i
                    join marts.dim_products p on i.product_key = p.product_key
                    where i.is_delivered
                    group by p.category
                )
                select round(sum(rev), 2) from by_category""",
    },
    {
        "for": "Q018",
        "name": "Orders per state sums back to the total order count",
        "a": "select count(*) from marts.fct_orders",
        "b": """with by_state as (
                    select c.customer_state, count(*) as n
                    from marts.fct_orders o
                    join marts.dim_customers c on o.customer_key = c.customer_key
                    group by c.customer_state
                )
                select sum(n) from by_state""",
    },
    {
        "for": "Q030",
        "name": "Products sold plus products never sold equals the catalogue",
        "a": "select count(*) from marts.dim_products",
        "b": """select
                    (select count(distinct product_key)
                     from marts.fct_order_items where is_delivered)
                  + (select count(*) from marts.dim_products p
                     where not exists (
                         select 1 from marts.fct_order_items i
                         where i.product_key = p.product_key and i.is_delivered))""",
    },
]


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    passed = failed = errored = 0

    for check in CHECKS:
        label = f"{check['for']:<10} {check['name']}"
        try:
            a = con.execute(check["a"]).fetchone()[0]
            b = con.execute(check["b"]).fetchone()[0]
        except Exception as e:
            errored += 1
            print(f"ERROR  {label}\n         {str(e).splitlines()[0]}")
            continue

        if a is None or b is None:
            agree = a is None and b is None
        else:
            agree = abs(float(a) - float(b)) <= TOLERANCE

        if agree:
            passed += 1
            print(f"PASS   {label}\n         both routes give {a}")
        else:
            failed += 1
            print(f"FAIL   {label}\n         route A = {a}\n         route B = {b}")

    con.close()
    print(f"\n{passed} passed, {failed} failed, {errored} errored "
          f"out of {len(CHECKS)} cross-checks.")


if __name__ == "__main__":
    main()
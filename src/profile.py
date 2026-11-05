"""Profile source and built tables, and verify the dimension layer."""

import duckdb
import pandas as pd

from src.config import DB_PATH

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

CHECKS = [

    # ---------- Source data ----------

    (
        "Order statuses",
        """
        select order_status, count(*) as n
        from raw.orders
        group by 1
        order by 2 desc
        """,
    ),
    (
        "Delivered-date coverage",
        """
        select
            count(*)                             as total_rows,
            count(order_delivered_customer_date) as delivered
        from raw.orders
        """,
    ),
    (
        "Customers vs people",
        """
        select
            count(*)                          as customer_rows,
            count(distinct customer_unique_id) as people
        from raw.customers
        """,
    ),
    (
        "Order items fan-out",
        """
        select
            count(*)                 as item_rows,
            count(distinct order_id) as orders
        from raw.order_items
        """,
    ),
    (
        "Geolocation duplicates",
        """
        select
            count(*)                                    as geo_rows,
            count(distinct geolocation_zip_code_prefix) as zips
        from raw.geolocation
        """,
    ),

    # ---------- Built dimension tables ----------

    (
        "dim_customers is one row per person",
        """
        select
            count(*)                     as rows_in_dim,
            count(distinct customer_key) as distinct_people,
            sum(order_count)             as orders_accounted_for,
            sum(case when is_repeat_customer then 1 else 0 end) as repeat_customers
        from marts.dim_customers
        """,
    ),
    (
        "dim_dates covers the full range",
        """
        select
            count(*)                    as days,
            min(date_key)               as first_day,
            max(date_key)               as last_day,
            count(distinct month_start) as months
        from marts.dim_dates
        """,
    ),
    (
        "dim_products categories",
        """
        select
            count(*)                 as products,
            count(distinct category) as categories,
            sum(case when category = 'unknown' then 1 else 0 end) as uncategorised
        from marts.dim_products
        """,
    ),

    # ---------- Category investigation ----------

    (
        "Where do uncategorised products come from?",
        """
        select
            case
                when p.category_name_pt is null  then 'A: no category in source'
                when t.category_name_en is null  then 'B: has category, no translation'
                else                                  'C: translated'
            end as situation,
            count(*) as products
        from staging.stg_products p
        left join staging.stg_category_translation t
            on p.category_name_pt = t.category_name_pt
        group by 1
        order by 2 desc
        """,
    ),
    (
        "Which categories have no translation?",
        """
        select
            p.category_name_pt,
            count(*) as products
        from staging.stg_products p
        left join staging.stg_category_translation t
            on p.category_name_pt = t.category_name_pt
        where p.category_name_pt is not null
          and t.category_name_en is null
        group by p.category_name_pt
        order by products desc
        """,
    ),
    (
        "Categories identical in both languages",
        """
        select category_name_pt, category_name_en
        from staging.stg_category_translation
        where category_name_pt = category_name_en
        order by 1
        """,
    ),
    (
        "Did the category overrides apply?",
        """
        select
            sum(case when category = 'gaming_pc' then 1 else 0 end) as gaming_pc,
            sum(case when category = 'portable_kitchen_and_food_preparers'
                     then 1 else 0 end)                             as kitchen,
            sum(case when category in ('pc_gamer',
                                       'portateis_cozinha_e_preparadores_de_alimentos')
                     then 1 else 0 end)                             as still_untranslated
        from marts.dim_products
        """,
    ),
    # ---------- Built fact tables ----------

    (
        "fct_orders has one row per order",
        """
        select
            count(*)                  as rows_in_fact,
            count(distinct order_key) as distinct_orders,
            sum(case when is_delivered then 1 else 0 end)   as delivered,
            sum(case when is_cancelled then 1 else 0 end)   as cancelled,
            sum(case when item_count = 0 then 1 else 0 end) as orders_with_no_items
        from marts.fct_orders
        """,
    ),
    (
        "Delivery timing coverage",
        """
        select
            count(*)                       as total_orders,
            count(days_to_deliver)         as have_delivery_time,
            round(avg(days_to_deliver), 1) as avg_days_to_deliver,
            sum(case when is_late then 1 else 0 end) as late_deliveries
        from marts.fct_orders
        """,
    ),
    (
        "The two totals must agree",
        """
        select
            (select sum(items_value) from marts.fct_orders)      as from_orders,
            (select sum(item_price)  from marts.fct_order_items) as from_items
        """,
    ),
    (
        "What a careless join costs you",
        """
        select
            (select sum(order_value) from marts.fct_orders) as correct_total,
            (select sum(o.order_value)
             from marts.fct_orders o
             join marts.fct_order_items i on o.order_key = i.order_key) as inflated_total
        """,
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
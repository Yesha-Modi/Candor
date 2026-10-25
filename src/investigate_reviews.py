"""Investigate the review_id uniqueness failure in stg_order_reviews."""

import duckdb
import pandas as pd

from src.config import DB_PATH

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

CHECKS = [
    (
        "Rows vs distinct review_id",
        """
        select
            count(*)                              as total_rows,
            count(distinct review_id)             as distinct_review_ids,
            count(*) - count(distinct review_id)  as excess_rows
        from staging.stg_order_reviews
        """,
    ),
    (
        "Rows vs distinct order_id",
        """
        select
            count(*)                             as total_rows,
            count(distinct order_id)             as distinct_order_ids,
            count(*) - count(distinct order_id)  as excess_rows
        from staging.stg_order_reviews
        """,
    ),
    (
        "How many review_ids repeat, and how badly",
        """
        with counts as (
            select review_id, count(*) as n
            from staging.stg_order_reviews
            group by review_id
        )
        select
            n                as rows_per_review_id,
            count(*)         as how_many_review_ids
        from counts
        group by n
        order by n
        """,
    ),
    (
        "Are the duplicated rows identical, or genuinely different?",
        """
        select count(*) as groups_that_agree
        from (
            select review_id
            from staging.stg_order_reviews
            group by review_id
            having count(*) > 1
               and count(distinct score) = 1
               and count(distinct coalesce(comment_message, '~none~')) = 1
        )
        """,
    ),
    (
        "Three duplicated review_ids, full detail",
        """
        with dupes as (
            select review_id
            from staging.stg_order_reviews
            group by review_id
            having count(*) > 1
            order by review_id
            limit 3
        )
        select
            r.review_id,
            r.order_id,
            r.score,
            r.created_at,
            left(coalesce(r.comment_message, ''), 40) as comment_start
        from staging.stg_order_reviews r
        join dupes d using (review_id)
        order by r.review_id, r.order_id
        """,
    ),
    (
        "Is the (review_id, order_id) pair unique?",
        """
        select
            count(*)                               as total_rows,
            count(distinct (review_id, order_id))   as distinct_pairs
        from staging.stg_order_reviews
        """,
    ),
    (
        "Orders carrying more than one review",
        """
        with multi as (
            select order_id
            from staging.stg_order_reviews
            group by order_id
            having count(*) > 1
            order by order_id
            limit 3
        )
        select
            r.order_id,
            r.review_id,
            r.score,
            r.created_at
        from staging.stg_order_reviews r
        join multi m using (order_id)
        order by r.order_id, r.created_at
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
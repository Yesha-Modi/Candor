"""One-time repair of the gold file, with every change explained.

    python fix_gold.py --dry-run
    python fix_gold.py

Why this exists: the first benchmark run scored 53%, and most of the failures
turned out to be defects in the gold queries rather than in the agent. Two
kinds, both mine:

1. **Gold queries returning columns the question never asked for.** These were
   written in Session 5 to be informative while being checked by hand -- an
   extra count(*) column made eyeballing easier. That purpose conflicts with
   their later use as a scoring reference, where an extra column is a shape
   mismatch. The same artifact served two jobs and the second one broke.

2. **Gold queries encoding a filter the question never stated** -- a
   `having count(*) >= 100` with nothing in the question about a threshold.
   A question whose answer depends on an unstated choice is an ambiguous
   question, so either the question states the threshold or it should never
   have been an `answer` question. Here the questions are reworded to state
   it, because the filter is the sensible analyst choice and the point of
   these items is the join, not the ambiguity.

Plus one gold query that was simply wrong (Q010) and one that was a diagnostic
rather than an answer (Q014).

Nothing here was changed to match what the agent produced. Each gold query is
reduced to exactly the columns its question asks for, and that rule was
applied to every affected question before looking at whether it changed the
verdict.
"""

import argparse
import io
import sys
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString as LS

GOLD = Path(__file__).resolve().parent / "eval" / "gold_questions.yaml"

# id -> (new_sql or None, new_question or None, reason)
FIXES: dict[str, tuple[str | None, str | None, str]] = {

    # --- gold query was wrong -------------------------------------------
    "Q010": (
        """select count(*) as late_orders
from marts.fct_orders
where is_delivered
  and is_late
""",
        None,
        "the question says DELIVERED orders; the gold counted all late orders, "
        "including the one late order that was never delivered (7827 vs 7826). "
        "The agent was right and the gold was wrong.",
    ),

    "Q014": (
        """select round(100.0 * count(*) filter (where is_late) / count(*), 2)
           as late_pct
from marts.fct_orders
where is_delivered
  and delivered_at is not null
""",
        None,
        "the gold was the four-column diagnostic from Session 5, not an answer. "
        "The question asks for a share, which is one number.",
    ),

    # --- drop columns the question does not ask for ----------------------
    "Q016": (
        """select
    p.category,
    round(sum(i.item_price), 2) as item_revenue
from marts.fct_order_items i
join marts.dim_products p on i.product_key = p.product_key
where i.is_delivered
group by p.category
order by item_revenue desc
limit 1
""",
        None,
        "renamed the output column from `revenue` to `item_revenue`: the gold "
        "had the same mislabelling the agent was flagged for in Session 8.",
    ),

    "Q019": (
        """select
    c.customer_state,
    round(avg(o.days_to_deliver), 2) as avg_days_to_deliver
from marts.fct_orders o
join marts.dim_customers c on o.customer_key = c.customer_key
where o.days_to_deliver is not null
group by c.customer_state
order by count(*) desc
limit 10
""",
        None,
        "dropped `delivered_orders`: it selects the ten states but is not part "
        "of the answer, and ordering by count(*) does not require selecting it.",
    ),

    "Q020": (
        """select
    s.seller_key,
    round(sum(i.item_price), 2) as item_revenue
from marts.fct_order_items i
join marts.dim_sellers s on i.seller_key = s.seller_key
where i.is_delivered
group by s.seller_key
order by item_revenue desc
limit 1
""",
        None,
        "dropped `seller_state`, which the question does not ask for.",
    ),

    "Q021": (
        """select
    i.seller_key,
    count(distinct p.category) as categories
from marts.fct_order_items i
join marts.dim_products p on i.product_key = p.product_key
where i.is_delivered
group by i.seller_key
order by sum(i.item_price) desc
limit 5
""",
        None,
        "dropped `revenue`: it ranks the sellers but is not the answer to "
        "'how many categories'.",
    ),

    "Q022": (
        """select
    p.category,
    round(avg(i.item_price), 2) as avg_item_price
from marts.fct_order_items i
join marts.dim_products p on i.product_key = p.product_key
where i.is_delivered
group by p.category
having count(*) >= 500
order by avg_item_price desc
""",
        None,
        "dropped `items_sold`: it is the HAVING threshold, already stated in "
        "the question, not a requested output.",
    ),

    "Q026": (
        """select
    c.customer_city,
    round(avg(o.order_value), 2) as avg_order_value
from marts.fct_orders o
join marts.dim_customers c on o.customer_key = c.customer_key
where o.is_delivered
group by c.customer_city
having count(*) >= 100
order by avg_order_value desc
limit 5
""",
        "Which five cities have the highest average order value among "
        "delivered orders, counting only cities with at least 100 delivered "
        "orders?",
        "dropped `orders`, and put the 100-order threshold into the question. "
        "Without it the top five cities are whichever had one expensive order, "
        "so the gold was answering a question it had not asked.",
    ),

    "Q027": (
        """select
    p.category,
    count(distinct o.order_key) as one_star_orders
from marts.fct_orders o
join marts.fct_order_items i on o.order_key = i.order_key
join marts.dim_products p on i.product_key = p.product_key
where o.is_delivered
  and o.worst_review_score = 1
group by p.category
order by one_star_orders desc
""",
        None,
        "removed `limit 10`: 'broken down by product category' asks for every "
        "category, not the top ten. The agent's 72 rows were right.",
    ),

    "Q028": (
        """with order_sellers as (
    select distinct
        i.order_key,
        s.seller_state
    from marts.fct_order_items i
    join marts.dim_sellers s on i.seller_key = s.seller_key
)
select
    os.seller_state,
    round(avg(o.days_to_deliver), 2) as avg_days_to_deliver
from order_sellers os
join marts.fct_orders o on os.order_key = o.order_key
where o.days_to_deliver is not null
group by os.seller_state
having count(*) >= 100
order by avg_days_to_deliver desc
""",
        "Which seller states have the worst average delivery time, among "
        "states with at least 100 delivered orders?",
        "dropped `orders` and stated the threshold in the question.",
    ),

    "Q017": (
        """with order_categories as (
    select distinct
        i.order_key,
        p.category
    from marts.fct_order_items i
    join marts.dim_products p on i.product_key = p.product_key
)
select
    oc.category,
    round(avg(o.review_score), 3) as avg_review_score
from order_categories oc
join marts.fct_orders o on oc.order_key = o.order_key
where o.review_count > 0
group by oc.category
having count(*) >= 100
order by avg_review_score asc
limit 5
""",
        "Which five product categories have the lowest average review score, "
        "among categories with at least 100 reviewed orders?",
        "dropped `orders` and stated the threshold in the question.",
    ),

    "Q023": (
        """select
    p.category,
    count(*) as items_bought
from marts.fct_order_items i
join marts.dim_products  p on i.product_key  = p.product_key
join marts.dim_customers c on i.customer_key = c.customer_key
where c.is_repeat_customer
  and i.is_delivered
group by p.category
order by items_bought desc
limit 10
""",
        "Which ten product categories do repeat customers buy most often?",
        "the gold had `limit 10` while the question named no number, so the "
        "agent's 71 rows were defensible. Pinned the count in the question "
        "rather than removing the limit, because a 'most often' ranking over "
        "all 71 categories is not what the question is for.",
    ),

    "Q025": (
        """select
    p.category,
    round(100.0 * sum(i.freight_price) / sum(i.item_price), 2)
        as freight_pct_of_price
from marts.fct_order_items i
join marts.dim_products p on i.product_key = p.product_key
where i.is_delivered
  and i.item_price > 0
group by p.category
having count(*) >= 100
order by freight_pct_of_price desc
""",
        "What is the average freight cost as a share of item price, by product "
        "category, among categories with at least 100 delivered items?",
        "dropped `items` and stated the threshold in the question.",
    ),

    # --- time series: all the same defect --------------------------------
    "Q031": (
        """select
    d.month_start,
    round(sum(o.order_value), 2) as revenue
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
where o.is_delivered
  and d.year = 2018
group by d.month_start
order by d.month_start
""",
        None,
        "dropped `orders`.",
    ),

    "Q032": (
        """select
    d.quarter_start,
    count(*) as orders
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
group by d.quarter_start
order by d.quarter_start
""",
        "How many orders were placed in each quarter, across all years? "
        "Identify each quarter by its start date.",
        "the gold split the quarter across two columns (year, quarter) while "
        "the agent used the single `quarter_start`. Both answer the question, "
        "so the question now pins the representation -- and `quarter_start` is "
        "the choice that matches `month_start` used in Q031, Q033 and Q035.",
    ),

    "Q033": (
        """select d.month_start
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
where o.is_delivered
group by d.month_start
order by count(*) desc
limit 1
""",
        None,
        "dropped `delivered_orders`: 'which month' asks for a month.",
    ),

    "Q034": (
        """with monthly as (
    select
        d.month_start,
        sum(o.order_value) as revenue
    from marts.fct_orders o
    join marts.dim_dates d on o.order_date = d.date_key
    where o.is_delivered
      and d.year = 2018
    group by d.month_start
)
select
    month_start,
    round(revenue - lag(revenue) over (order by month_start), 2)
        as change_vs_prior
from monthly
order by month_start
""",
        None,
        "dropped `revenue` and `pct_change`: the question asks for the change.",
    ),

    "Q035": (
        """select
    d.month_start,
    round(avg(o.days_to_deliver), 2) as avg_days_to_deliver
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
where o.days_to_deliver is not null
  and d.year = 2018
group by d.month_start
order by d.month_start
""",
        None,
        "dropped `delivered_orders`.",
    ),

    "Q036": (
        """with monthly as (
    select
        d.month_start,
        sum(o.order_value) as revenue
    from marts.fct_orders o
    join marts.dim_dates d on o.order_date = d.date_key
    where o.is_delivered
    group by d.month_start
)
select
    month_start,
    round(sum(revenue) over (order by month_start), 2) as cumulative_revenue
from monthly
order by month_start
""",
        None,
        "dropped the per-month `revenue`: the question asks for cumulative.",
    ),

    "Q037": (
        """select
    d.is_weekend,
    round(avg(o.order_value), 2) as avg_order_value
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
where o.is_delivered
group by d.is_weekend
order by d.is_weekend
""",
        None,
        "dropped `orders`.",
    ),

    "Q038": (
        """select d.day_name
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
group by d.day_name
order by count(*) desc
limit 1
""",
        None,
        "dropped `orders`: 'which day' asks for a day.",
    ),

    "Q039": (
        """select
    d.year,
    round(avg(o.review_score), 3) as avg_review_score
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
where o.review_count > 0
group by d.year
order by d.year
""",
        None,
        "dropped `reviewed_orders`.",
    ),

    "Q040": (
        """select
    d.month_start,
    round(100.0 * count(*) filter (where o.is_late) / count(*), 2) as late_pct
from marts.fct_orders o
join marts.dim_dates d on o.order_date = d.date_key
where o.is_delivered
  and o.delivered_at is not null
  and d.year = 2018
group by d.month_start
order by d.month_start
""",
        None,
        "dropped `delivered_orders` and `late_orders`: the question asks for "
        "the share.",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would change and write nothing")
    args = parser.parse_args()

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096

    with open(GOLD, encoding="utf-8") as f:
        questions = yaml.load(f)

    by_id = {q["id"]: q for q in questions}
    missing = sorted(set(FIXES) - set(by_id))
    if missing:
        sys.exit(f"these ids are not in the gold file: {missing}")

    changed = 0
    for qid, (new_sql, new_question, reason) in FIXES.items():
        q = by_id[qid]
        edits = []

        if new_question and q["question"] != new_question:
            q["question"] = new_question
            edits.append("question")

        if new_sql and q.get("sql", "").strip() != new_sql.strip():
            q["sql"] = LS(new_sql)
            edits.append("sql")

        if edits:
            changed += 1
            note = str(q.get("notes") or "")
            stamp = f"Gold corrected in Session 10: {reason}"
            if stamp not in note:
                q["notes"] = (note + " " + stamp).strip()
            print(f"{qid}  {'+'.join(edits)}")
            print(f"      {reason}\n")

    if args.dry_run:
        print(f"{changed} entries would change. Nothing written (--dry-run).")
        return

    buf = io.StringIO()
    yaml.dump(questions, buf)
    GOLD.write_text(buf.getvalue(), encoding="utf-8")
    print(f"{changed} entries updated in {GOLD}")
    print("Review with:  git diff eval/gold_questions.yaml")


if __name__ == "__main__":
    main()
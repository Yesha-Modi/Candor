"""Prove the failure classifier assigns the tag it should.

    python -m eval.check_taxonomy

Every case below is a failure that actually happened in a benchmark run, with
the SQL the model actually produced. None of them is invented, which matters:
a classifier tested only on cases written to suit it will agree with itself
and tell you nothing.

Exits non-zero if any case is tagged wrongly.
"""

import sys

from agent.prompt import load_layer
from eval.taxonomy import classify

CASES = [
    ("fan-out: avg of an order column after joining items",
     dict(verdict="value_mismatch",
          detail="12 of 13 rows differ; first DIFFERENCE at gold ('BA', 13.79) "
                 "vs agent ('BA', 13.77)",
          sql="SELECT s.seller_state, AVG(o.days_to_deliver) AS d "
              "FROM marts.fct_orders o "
              "JOIN marts.fct_order_items oi ON o.order_key = oi.order_key "
              "JOIN marts.dim_sellers s ON oi.seller_key = s.seller_key "
              "GROUP BY 1"),
     dict(sql="with os as (select distinct i.order_key, s.seller_state "
              "from marts.fct_order_items i join marts.dim_sellers s "
              "on i.seller_key = s.seller_key) "
              "select os.seller_state, round(avg(o.days_to_deliver), 2) "
              "from os join marts.fct_orders o on os.order_key = o.order_key "
              "group by 1"),
     "fan_out"),

    ("column substitution: item_total includes freight",
     dict(verdict="value_mismatch",
          detail="1 of 1 rows differ; first DIFFERENCE at gold ('4869', "
                 "226987.93) vs agent ('4869', 247007.06)",
          sql="SELECT seller_key, ROUND(SUM(item_total), 2) AS r "
              "FROM marts.fct_order_items WHERE is_delivered = TRUE "
              "GROUP BY seller_key ORDER BY r DESC LIMIT 1"),
     dict(sql="select s.seller_key, round(sum(i.item_price), 2) as item_revenue "
              "from marts.fct_order_items i join marts.dim_sellers s "
              "on i.seller_key = s.seller_key where i.is_delivered "
              "group by 1 order by 2 desc limit 1"),
     "column_substitution"),

    ("meaningless grouping: 'April' across three years",
     dict(verdict="value_mismatch",
          detail="8 of 8 rows differ; first DIFFERENCE at gold "
                 "('2018-01-01 00:00:00', 1077887.46) vs agent ('April', 1132878.93)",
          sql="SELECT d.month_name, ROUND(SUM(o.order_value), 2) AS r "
              "FROM marts.fct_orders AS o JOIN marts.dim_dates AS d "
              "ON o.order_date = d.date_key "
              "WHERE o.is_delivered AND d.year = 2018 GROUP BY d.month_name"),
     dict(sql="select d.month_start, round(sum(o.order_value), 2) as revenue "
              "from marts.fct_orders o join marts.dim_dates d "
              "on o.order_date = d.date_key where o.is_delivered "
              "and d.year = 2018 group by d.month_start order by d.month_start"),
     "meaningless_grouping"),

    ("missing filter: no is_delivered",
     dict(verdict="value_mismatch",
          detail="2 of 2 rows differ; first DIFFERENCE at gold (0.0, 160.27) "
                 "vs agent (0.0, 159.71)",
          sql="SELECT d.is_weekend, ROUND(AVG(o.order_value), 2) AS a "
              "FROM marts.fct_orders AS o JOIN marts.dim_dates AS d "
              "ON o.order_date = d.date_key GROUP BY d.is_weekend"),
     dict(sql="select d.is_weekend, round(avg(o.order_value), 2) "
              "from marts.fct_orders o join marts.dim_dates d "
              "on o.order_date = d.date_key where o.is_delivered "
              "group by d.is_weekend"),
     "missing_filter"),

    ("missing window function: monthly instead of cumulative",
     dict(verdict="value_mismatch",
          detail="22 of 23 rows differ; first DIFFERENCE at gold "
                 "('2016-10-01 00:00:00', 46634.12) vs agent "
                 "('2016-10-01 00:00:00', 46490.66)",
          sql="SELECT d.month_start, round(sum(o.order_value), 2) "
              "FROM marts.fct_orders AS o JOIN marts.dim_dates AS d "
              "ON o.order_date = d.date_key WHERE o.is_delivered "
              "GROUP BY 1 ORDER BY 1"),
     dict(sql="with monthly as (select d.month_start, sum(o.order_value) as revenue "
              "from marts.fct_orders o join marts.dim_dates d "
              "on o.order_date = d.date_key where o.is_delivered "
              "group by d.month_start) select month_start, "
              "round(sum(revenue) over (order by month_start), 2) from monthly"),
     "missing_window_function"),

    ("units: out by a factor of 100",
     dict(verdict="value_mismatch",
          detail="54 of 54 rows differ; first DIFFERENCE at gold ('agro', 7.99) "
                 "vs agent ('agro', 0.08)",
          sql="SELECT p.category, ROUND(SUM(oi.freight_price) / "
              "SUM(oi.item_price), 2) AS s FROM marts.fct_order_items oi "
              "JOIN marts.dim_products p ON oi.product_key = p.product_key "
              "WHERE oi.is_delivered GROUP BY 1"),
     dict(sql="select p.category, round(100.0 * sum(i.freight_price) / "
              "sum(i.item_price), 2) from marts.fct_order_items i "
              "join marts.dim_products p on i.product_key = p.product_key "
              "where i.is_delivered and i.item_price > 0 group by p.category"),
     "units_mismatch"),

    ("over-answering: extra columns, same rows",
     dict(verdict="shape_mismatch", detail="gold 1x1, agent 1x3",
          sql="SELECT d.month_name, d.year, count(o.order_key) AS c "
              "FROM marts.fct_orders AS o JOIN marts.dim_dates AS d "
              "ON o.order_date = d.date_key WHERE o.is_delivered "
              "GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1"),
     dict(sql="select d.month_start from marts.fct_orders o "
              "join marts.dim_dates d on o.order_date = d.date_key "
              "where o.is_delivered group by d.month_start "
              "order by count(*) desc limit 1"),
     "over_answering"),

    ("invented column",
     dict(verdict="sql_error",
          detail='BinderException: Table "t2" does not have a column '
                 'named "seller_id"',
          sql="SELECT t2.seller_id, round(sum(t1.item_price), 2) "
              "FROM marts.fct_order_items AS t1 JOIN marts.dim_sellers AS t2 "
              "ON t1.seller_key = t2.seller_key GROUP BY 1"),
     dict(sql="select s.seller_key, round(sum(i.item_price), 2) "
              "from marts.fct_order_items i join marts.dim_sellers s "
              "on i.seller_key = s.seller_key group by 1"),
     "invented_column"),

    ("answered what should have been clarified",
     dict(verdict="decision_wrong", expected="clarify", decision="answer",
          detail="expected clarify, got answer", sql=None),
     dict(sql=None),
     "wrong_decision_clarify_got_answer"),

    ("a correct answer is not a failure",
     dict(verdict="match", detail="",
          sql="select count(*) from marts.fct_orders"),
     dict(sql="select count(*) as total_orders from marts.fct_orders"),
     "correct"),
]


def metric_case(metric_names: set[str]) -> tuple:
    """Build the metric-as-column case from a metric that really exists.

    Hard-coding a metric name here made this test depend on the semantic
    layer keeping that particular metric -- so the test failed for a reason
    that had nothing to do with the classifier. Taking the name from the
    layer tests the RULE instead of one instance of it.
    """
    name = sorted(metric_names)[0]
    return (
        f"metric name used as a column ({name})",
        dict(verdict="sql_error",
             detail=f'BinderException: Referenced column "{name}" '
                    f'not found in FROM clause!',
             sql=f"SELECT {name} FROM marts.fct_orders"),
        dict(sql="select count(*) from marts.fct_orders"),
        "metric_used_as_column",
    )


def main() -> None:
    layer = load_layer()
    metric_names = {m["name"].lower() for m in layer["metrics"]}
    if not metric_names:
        raise SystemExit("the semantic layer declares no metrics")

    cases = CASES + [metric_case(metric_names)]

    wrong = 0
    for label, record, gold, expected in cases:
        got = classify(record, gold, metric_names)
        if got == expected:
            print(f"  ok     {label}")
        else:
            wrong += 1
            print(f"  WRONG  {label}")
            print(f"         expected {expected!r}, got {got!r}")

    print(f"\n{len(cases) - wrong}/{len(cases)} correct")
    if wrong:
        print("The classifier does not agree with its own specification.")
        sys.exit(1)


if __name__ == "__main__":
    main()
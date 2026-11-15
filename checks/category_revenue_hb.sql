-- Agent question 4: "Which product category generated the most revenue?"
-- Expect health_beauty at 1233131.72 -- matching Q016 in the gold set,
-- computed independently in Session 7 before the agent existed.
--
-- The metric is item_revenue, not revenue: freight is not attributable to a
-- product, so including it would inflate every category by its shipping.
select
    p.category,
    round(sum(i.item_price), 2) as item_revenue
from marts.fct_order_items i
join marts.dim_products p on i.product_key = p.product_key
where i.is_delivered
group by 1
order by 2 desc
limit 5;
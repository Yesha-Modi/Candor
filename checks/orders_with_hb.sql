-- Route b for "how many orders included a health and beauty product?"
-- Route a (the agent's) was count(distinct order_key) off fct_order_items.
-- This drives off fct_orders with a semi-join instead. Expect 8,836.
select count(*) as orders_with_hb
from marts.fct_orders o
where exists (
    select 1
    from marts.fct_order_items i
    join marts.dim_products p on i.product_key = p.product_key
    where i.order_key = o.order_key
      and p.category = 'health_beauty'
);
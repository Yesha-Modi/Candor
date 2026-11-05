with from_orders as (

    select sum(items_value) as total from {{ ref('fct_orders') }}

),

from_items as (

    select sum(item_price) as total from {{ ref('fct_order_items') }}

)

select
    o.total as orders_total,
    i.total as items_total

from from_orders o
cross join from_items i

where abs(o.total - i.total) > 0.01
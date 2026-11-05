with items as (

    select * from {{ ref('stg_order_items') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

)

select
    i.order_id || '-' || i.item_number  as order_item_key,

    i.order_id            as order_key,
    i.item_number,
    i.product_id          as product_key,
    i.seller_id           as seller_key,
    c.customer_unique_id  as customer_key,
    o.purchased_at::date  as order_date,

    o.status,
    o.status = 'delivered' as is_delivered,

    i.item_price,
    i.freight_price,
    i.item_price + i.freight_price as item_total

from items i
inner join orders    o on i.order_id = o.order_id
inner join customers c on o.customer_id = c.customer_id
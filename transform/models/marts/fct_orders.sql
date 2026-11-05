with orders as (

    select * from {{ ref('stg_orders') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

),

items_per_order as (

    select
        order_id,
        count(*)                    as item_count,
        count(distinct product_id)  as distinct_product_count,
        count(distinct seller_id)   as seller_count,
        sum(item_price)             as items_value,
        sum(freight_price)          as freight_value

    from {{ ref('stg_order_items') }}
    group by order_id

),

payments_per_order as (

    select
        order_id,
        sum(payment_amount) as amount_paid,
        count(*)            as payment_count,
        max(installments)   as max_installments

    from {{ ref('stg_order_payments') }}
    group by order_id

),

reviews_per_order as (

    select
        order_id,
        avg(score)::decimal(3,2) as review_score,
        count(*)                 as review_count,
        min(score)               as worst_review_score

    from {{ ref('stg_order_reviews') }}
    group by order_id

)

select
    o.order_id             as order_key,
    c.customer_unique_id   as customer_key,
    o.purchased_at::date   as order_date,

    o.status,
    o.status = 'delivered'                   as is_delivered,
    o.status in ('canceled', 'unavailable')  as is_cancelled,

    o.purchased_at,
    o.approved_at,
    o.shipped_at,
    o.delivered_at,
    o.estimated_delivery_at,

    date_diff('day', o.purchased_at, o.delivered_at)           as days_to_deliver,
    date_diff('day', o.purchased_at, o.shipped_at)             as days_to_ship,
    date_diff('day', o.estimated_delivery_at, o.delivered_at)  as days_vs_estimate,

    case
        when o.delivered_at is null then null
        when o.delivered_at > o.estimated_delivery_at then true
        else false
    end as is_late,

    coalesce(i.item_count, 0)              as item_count,
    coalesce(i.distinct_product_count, 0)  as distinct_product_count,
    coalesce(i.seller_count, 0)            as seller_count,
    i.items_value,
    i.freight_value,
    coalesce(i.items_value, 0) + coalesce(i.freight_value, 0) as order_value,

    p.amount_paid,
    coalesce(p.payment_count, 0) as payment_count,
    p.max_installments,

    r.review_score,
    coalesce(r.review_count, 0) as review_count,
    r.worst_review_score

from orders o
inner join customers c           on o.customer_id = c.customer_id
left  join items_per_order    i  on o.order_id = i.order_id
left  join payments_per_order p  on o.order_id = p.order_id
left  join reviews_per_order  r  on o.order_id = r.order_id
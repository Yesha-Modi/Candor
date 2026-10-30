with customers as (

    select * from {{ ref('stg_customers') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

geo as (

    select * from {{ ref('stg_geolocation') }}

),

customer_orders as (

    select
        c.customer_unique_id,
        c.zip_code_prefix,
        c.city  as customer_city,
        c.state as customer_state,

        row_number() over (
            partition by c.customer_unique_id
            order by o.purchased_at desc, o.order_id
        ) as recency_rank,

        count(*)            over (partition by c.customer_unique_id) as order_count,
        min(o.purchased_at) over (partition by c.customer_unique_id) as first_order_at,
        max(o.purchased_at) over (partition by c.customer_unique_id) as last_order_at

    from customers c
    inner join orders o on c.customer_id = o.customer_id

)

select
    co.customer_unique_id as customer_key,
    co.zip_code_prefix,
    co.customer_city,
    co.customer_state,
    g.latitude,
    g.longitude,
    co.order_count,
    co.order_count > 1 as is_repeat_customer,
    co.first_order_at,
    co.last_order_at

from customer_orders co
left join geo g on co.zip_code_prefix = g.zip_code_prefix

where co.recency_rank = 1
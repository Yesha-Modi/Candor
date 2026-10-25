with source as (

    select * from {{ source('raw', 'order_items') }}

)

select
    order_id,
    order_item_id       as item_number,
    product_id,
    seller_id,
    shipping_limit_date as shipping_limit_at,
    price               as item_price,
    freight_value       as freight_price

from source
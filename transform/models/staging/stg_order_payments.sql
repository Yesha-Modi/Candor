with source as (

    select * from {{ source('raw', 'order_payments') }}

)

select
    order_id,
    payment_sequential   as payment_number,
    payment_type,
    payment_installments as installments,
    payment_value        as payment_amount

from source
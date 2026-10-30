with sellers as (

    select * from {{ ref('stg_sellers') }}

),

geo as (

    select * from {{ ref('stg_geolocation') }}

)

select
    s.seller_id as seller_key,
    s.zip_code_prefix,
    s.city  as seller_city,
    s.state as seller_state,
    g.latitude,
    g.longitude

from sellers s
left join geo g on s.zip_code_prefix = g.zip_code_prefix
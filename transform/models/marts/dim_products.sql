with products as (

    select * from {{ ref('stg_products') }}

),

translation as (

    select * from {{ ref('stg_category_translation') }}

)

select
    p.product_id as product_key,

    coalesce(t.category_name_en, 'unknown') as category,
    p.category_name_pt                      as category_portuguese,

    p.weight_grams,
    p.length_cm * p.height_cm * p.width_cm  as volume_cm3,

    p.photo_count,
    p.name_length,
    p.description_length

from products p
left join translation t on p.category_name_pt = t.category_name_pt
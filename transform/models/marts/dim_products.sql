with products as (

    select * from {{ ref('stg_products') }}

),

translation as (

    select * from {{ ref('stg_category_translation') }}

),

overrides as (

    select * from {{ ref('category_translation_overrides') }}

)

select
    p.product_id as product_key,

    coalesce(t.category_name_en,
             o.category_name_en,
             p.category_name_pt,
             'unknown')                     as category,
    p.category_name_pt                      as category_portuguese,

    p.weight_grams,
    p.length_cm * p.height_cm * p.width_cm  as volume_cm3,

    p.photo_count,
    p.name_length,
    p.description_length

from products p
left join translation t on p.category_name_pt = t.category_name_pt
left join overrides   o on p.category_name_pt = o.category_name_pt
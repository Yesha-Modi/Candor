select
    review_id,
    order_id,
    count(*) as rows_in_pair

from {{ ref('stg_order_reviews') }}

group by review_id, order_id
having count(*) > 1
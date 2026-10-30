with bounds as (

    select
        date_trunc('year', min(purchased_at))::date as start_date,
        (date_trunc('year', max(purchased_at))
            + interval 1 year
            - interval 1 day)::date                 as end_date

    from {{ ref('stg_orders') }}

),

calendar as (

    select unnest(generate_series(
        (select start_date from bounds),
        (select end_date   from bounds),
        interval 1 day
    ))::date as date_day

)

select
    date_day                              as date_key,

    year(date_day)                        as year,
    quarter(date_day)                     as quarter,
    month(date_day)                       as month,
    monthname(date_day)                   as month_name,
    day(date_day)                         as day_of_month,
    dayname(date_day)                     as day_name,

    date_trunc('month',   date_day)::date as month_start,
    date_trunc('quarter', date_day)::date as quarter_start,

    dayofweek(date_day) in (0, 6)         as is_weekend

from calendar
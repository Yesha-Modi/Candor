with source as (

    select * from {{ source('raw', 'geolocation') }}

),

ranked as (

    select
        geolocation_zip_code_prefix as zip_code_prefix,
        geolocation_lat             as latitude,
        geolocation_lng             as longitude,
        geolocation_city            as city,
        geolocation_state           as state,

        row_number() over (
            partition by geolocation_zip_code_prefix
            order by geolocation_lat, geolocation_lng
        ) as row_num

    from source

)

select
    zip_code_prefix,
    latitude,
    longitude,
    city,
    state

from ranked
where row_num = 1
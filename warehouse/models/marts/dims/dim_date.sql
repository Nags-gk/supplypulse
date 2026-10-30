with bounds as (
    select min(order_date) as first_day, max(ship_date) as last_day
    from {{ ref('stg_order_items') }}
)
select
    cast(d as date)                                 as date_key,
    year(d)                                         as year,
    quarter(d)                                      as quarter,
    month(d)                                        as month,
    strftime(d, '%Y-%m')                            as year_month,
    cast(date_trunc('week', d) as date)             as week_start,
    isodow(d)                                       as iso_day_of_week,
    isodow(d) in (6, 7)                             as is_weekend
from bounds, generate_series(first_day, last_day, interval 1 day) as t(d)

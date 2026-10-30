-- Forecasting input: weekly units and net sales per market x department, zero-filled so every
-- series has a value in every week of its active range.
with weekly as (
    select
        d.week_start,
        g.market,
        p.department_name,
        sum(f.units)     as units,
        sum(f.net_sales) as net_sales,
        count(*)         as order_lines
    from {{ ref('fct_order_items') }} as f
    join {{ ref('dim_date') }} as d on d.date_key = f.order_date
    join (select distinct geography_key, market from {{ ref('dim_geography') }}) as g using (geography_key)
    join {{ ref('dim_product') }} as p using (product_id)
    group by 1, 2, 3
),
weeks as (select distinct week_start from {{ ref('dim_date') }}),
series as (select distinct market, department_name from weekly),
bounds as (select max(week_start) as last_week from weekly)
select
    w.week_start,
    s.market,
    s.department_name,
    coalesce(k.units, 0)       as units,
    coalesce(k.net_sales, 0)   as net_sales,
    coalesce(k.order_lines, 0) as order_lines
from weeks as w
cross join series as s
cross join bounds as b
left join weekly as k
    on k.week_start = w.week_start and k.market = s.market and k.department_name = s.department_name
where w.week_start <= b.last_week

-- Daily KPIs by market. On-time delivery is measured on lines that were not shipping-cancelled.
select
    f.order_date,
    g.market,
    count(*)                                                         as order_lines,
    count(distinct f.order_id)                                       as orders,
    sum(f.units)                                                     as units,
    sum(f.net_sales)                                                 as net_sales,
    sum(f.profit)                                                    as profit,
    sum(f.is_on_time)                                                as on_time_lines,
    sum(1 - f.is_shipping_canceled)                                  as deliverable_lines,
    sum(f.is_late)                                                   as late_lines,
    sum(f.is_order_canceled)                                         as canceled_lines,
    sum(f.is_suspected_fraud)                                        as fraud_lines,
    sum(f.delay_days) filter (where f.is_shipping_canceled = 0)      as delay_days_total
from {{ ref('fct_order_items') }} as f
join (select distinct geography_key, market from {{ ref('dim_geography') }}) as g using (geography_key)
group by 1, 2

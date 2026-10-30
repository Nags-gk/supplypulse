-- Carrier-style scorecard: the dataset has no supplier or carrier id, so shipping mode is the closest grain.
select
    f.shipping_mode,
    m.speed_rank,
    count(*)                                                                         as order_lines,
    round(avg(f.shipping_days_scheduled), 2)                                         as avg_days_scheduled,
    round(avg(f.shipping_days_actual) filter (where f.is_shipping_canceled = 0), 2)  as avg_days_actual,
    round(avg(f.delay_days) filter (where f.is_shipping_canceled = 0), 3)            as avg_delay_days,
    round(sum(f.is_on_time) * 1.0 / nullif(sum(1 - f.is_shipping_canceled), 0), 4)   as on_time_delivery_rate,
    round(sum(f.is_late) * 1.0 / nullif(sum(1 - f.is_shipping_canceled), 0), 4)      as late_delivery_rate,
    round(sum(f.profit) / nullif(sum(f.net_sales), 0), 4)                            as profit_margin
from {{ ref('fct_order_items') }} as f
join {{ ref('dim_shipping_mode') }} as m using (shipping_mode)
group by 1, 2

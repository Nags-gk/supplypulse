select
    d.year_month,
    k.market,
    sum(k.order_lines)                                                     as order_lines,
    sum(k.orders)                                                          as orders_approx,
    sum(k.units)                                                           as units,
    round(sum(k.net_sales), 2)                                             as net_sales,
    round(sum(k.profit), 2)                                                as profit,
    round(sum(k.profit) / nullif(sum(k.net_sales), 0), 4)                  as profit_margin,
    round(sum(k.on_time_lines) * 1.0 / nullif(sum(k.deliverable_lines), 0), 4) as on_time_delivery_rate,
    round(sum(k.late_lines) * 1.0 / nullif(sum(k.deliverable_lines), 0), 4)    as late_delivery_rate,
    round(sum(k.delay_days_total) * 1.0 / nullif(sum(k.deliverable_lines), 0), 3) as avg_delay_days,
    round(sum(k.canceled_lines) * 1.0 / nullif(sum(k.order_lines), 0), 4)  as cancellation_rate,
    round(sum(k.fraud_lines) * 1.0 / nullif(sum(k.order_lines), 0), 4)     as suspected_fraud_rate
from {{ ref('kpi_daily') }} as k
join {{ ref('dim_date') }} as d on d.date_key = k.order_date
group by 1, 2

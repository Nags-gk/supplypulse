select
    g.market,
    g.order_region,
    count(*)                                                                         as order_lines,
    round(sum(f.net_sales), 2)                                                       as net_sales,
    round(sum(f.is_on_time) * 1.0 / nullif(sum(1 - f.is_shipping_canceled), 0), 4)   as on_time_delivery_rate,
    round(avg(f.delay_days) filter (where f.is_shipping_canceled = 0), 3)            as avg_delay_days,
    round(sum(f.profit) / nullif(sum(f.net_sales), 0), 4)                            as profit_margin,
    round(sum(f.is_suspected_fraud) * 1.0 / count(*), 4)                             as suspected_fraud_rate
from {{ ref('fct_order_items') }} as f
join {{ ref('dim_geography') }} as g using (geography_key)
group by 1, 2

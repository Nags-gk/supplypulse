select
    p.department_name,
    p.category_name,
    count(*)                                                                         as order_lines,
    sum(f.units)                                                                     as units,
    round(sum(f.net_sales), 2)                                                       as net_sales,
    round(sum(f.profit) / nullif(sum(f.net_sales), 0), 4)                            as profit_margin,
    round(avg(f.discount_rate), 4)                                                   as avg_discount_rate,
    round(sum(f.is_on_time) * 1.0 / nullif(sum(1 - f.is_shipping_canceled), 0), 4)   as on_time_delivery_rate
from {{ ref('fct_order_items') }} as f
join {{ ref('dim_product') }} as p using (product_id)
group by 1, 2

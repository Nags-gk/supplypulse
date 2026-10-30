-- Customer attributes at their most recent order. No names, emails or street addresses are kept.
select
    customer_id,
    customer_segment,
    customer_city,
    customer_state,
    customer_country
from {{ ref('stg_order_items') }}
qualify row_number() over (partition by customer_id order by order_ts desc, order_item_id desc) = 1

-- Latest known attributes per product.
select
    product_id,
    product_name,
    product_price,
    category_id,
    category_name,
    department_id,
    department_name
from {{ ref('stg_order_items') }}
qualify row_number() over (partition by product_id order by order_ts desc, order_item_id desc) = 1

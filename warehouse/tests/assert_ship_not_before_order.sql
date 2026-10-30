-- Shipping can never precede the order (the ETL gate should already guarantee this).
select order_item_id from {{ ref('fct_order_items') }} where ship_date < order_date

-- Net sales should equal gross sales minus discount within a cent of rounding error.
select order_item_id from {{ ref('fct_order_items') }}
where abs(net_sales - (gross_sales - discount_amount)) > 0.05

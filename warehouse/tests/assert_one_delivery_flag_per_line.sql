-- Each line is exactly one of: on time, late, or shipping cancelled.
select order_item_id from {{ ref('fct_order_items') }}
where is_on_time + is_late + is_shipping_canceled <> 1

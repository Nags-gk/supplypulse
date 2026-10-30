select * from {{ ref('kpi_monthly') }}
where on_time_delivery_rate not between 0 and 1
   or late_delivery_rate not between 0 and 1
   or cancellation_rate not between 0 and 1
   or suspected_fraud_rate not between 0 and 1

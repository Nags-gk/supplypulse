-- Order destination hierarchy: market > region > country > state > city.
select distinct
    md5(concat_ws('|', market, order_region, order_country, order_state, order_city)) as geography_key,
    market,
    order_region,
    order_country,
    order_state,
    order_city
from {{ ref('stg_order_items') }}

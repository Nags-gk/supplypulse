select
    shipping_mode,
    case shipping_mode
        when 'Same Day' then 1
        when 'First Class' then 2
        when 'Second Class' then 3
        when 'Standard Class' then 4
    end as speed_rank
from (select distinct shipping_mode from {{ ref('stg_order_items') }})

-- Aggregated lines in the KPI mart must equal fact rows.
select 1
from (select sum(order_lines) as kpi_lines from {{ ref('kpi_daily') }}) k,
     (select count(*) as fact_lines from {{ ref('fct_order_items') }}) f
where k.kpi_lines <> f.fact_lines

"""Gold questions for the text-to-SQL agent. `gold` is None when the data cannot answer the question."""
J_G = "join dim_geography g using (geography_key)"
J_P = "join dim_product p using (product_id)"
J_D = "join dim_date d on d.date_key = f.order_date"

CASES = [
    ("How many order lines are there in total?", "select count(*) from fct_order_items"),
    ("How many distinct orders were placed?", "select count(distinct order_id) from fct_order_items"),
    ("What is the overall on-time delivery rate?", "select sum(is_on_time)*1.0/sum(1-is_shipping_canceled) from fct_order_items"),
    ("Which shipping mode has the highest late delivery rate?",
     "select shipping_mode from fct_order_items where is_shipping_canceled=0 group by 1 order by sum(is_late)*1.0/count(*) desc limit 1"),
    ("What is total net sales by market?", f"select g.market, sum(f.net_sales) from fct_order_items f {J_G} group by 1"),
    ("Which department has the highest total profit?",
     f"select p.department_name from fct_order_items f {J_P} group by 1 order by sum(f.profit) desc limit 1"),
    ("How many order lines were placed in 2016?", f"select count(*) from fct_order_items f {J_D} where d.year = 2016"),
    ("What is the profit margin for the Europe market?",
     f"select sum(f.profit)/sum(f.net_sales) from fct_order_items f {J_G} where g.market='Europe'"),
    ("What is the average delay in days for Standard Class shipments that were not canceled?",
     "select avg(delay_days) from fct_order_items where shipping_mode='Standard Class' and is_shipping_canceled=0"),
    ("How many orders have status SUSPECTED_FRAUD?", "select count(distinct order_id) from fct_order_items where order_status='SUSPECTED_FRAUD'"),
    ("What are the top 5 product categories by units sold?",
     f"select p.category_name from fct_order_items f {J_P} group by 1 order by sum(f.units) desc limit 5"),
    ("What was the cancellation rate in 2015?", f"select avg(f.is_order_canceled) from fct_order_items f {J_D} where d.year = 2015"),
    ("Which month had the most order lines?",
     f"select d.year_month from fct_order_items f {J_D} group by 1 order by count(*) desc limit 1"),
    ("How many distinct customers ordered from the LATAM market?",
     f"select count(distinct f.customer_id) from fct_order_items f {J_G} where g.market='LATAM'"),
    ("What is the average discount rate overall?", "select avg(discount_rate) from fct_order_items"),
    ("What is our inventory turnover?", None),
    ("Which supplier has the worst on-time-in-full performance?", None),
]

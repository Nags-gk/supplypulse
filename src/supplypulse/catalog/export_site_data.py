"""Export KPI marts and scorecards as compact JSON for the static dashboard."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import duckdb


def rows(con, sql: str) -> list[dict]:
    df = con.execute(sql).df()
    return json.loads(df.to_json(orient="records", date_format="iso"))


def run(db: str, out_dir: str, etl_report: str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db, read_only=True)
    try:
        overview = con.execute("""
            select count(*) as order_lines, count(distinct order_id) as orders, count(distinct customer_id) as customers,
                   count(distinct product_id) as products, sum(net_sales) as net_sales, sum(profit) as profit,
                   min(order_date) as first_order, max(order_date) as last_order
            from fct_order_items""").df().iloc[0].to_dict()
        overview = {k: (str(v)[:10] if k.endswith("order") else float(v) if k in ("net_sales", "profit") else int(v)) for k, v in overview.items()}
        data = {
            "overview": overview,
            "kpi_monthly": rows(con, "select * from kpi_monthly order by year_month, market"),
            "scorecard_shipping_mode": rows(con, "select * from scorecard_shipping_mode order by speed_rank"),
            "scorecard_region": rows(con, "select * from scorecard_region order by net_sales desc"),
            "scorecard_category": rows(con, "select * from scorecard_category order by net_sales desc"),
            "payment_type": rows(con, """select payment_type, count(*) as order_lines,
                round(avg(is_suspected_fraud), 4) as suspected_fraud_rate,
                round(sum(is_on_time) * 1.0 / sum(1 - is_shipping_canceled), 4) as on_time_delivery_rate
                from fct_order_items group by 1 order by 2 desc"""),
        }
    finally:
        con.close()
    for name, payload in data.items():
        (out / f"{name}.json").write_text(json.dumps(payload, separators=(",", ":")))
    if Path(etl_report).exists():
        shutil.copy(etl_report, out / "etl_report.json")
    return {k: (len(v) if isinstance(v, list) else 1) for k, v in data.items()}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/supplypulse.duckdb")
    p.add_argument("--out", default="site/data")
    p.add_argument("--etl-report", default="data/exports/etl_report.json")
    a = p.parse_args()
    print(run(a.db, a.out, a.etl_report))


if __name__ == "__main__":
    main()

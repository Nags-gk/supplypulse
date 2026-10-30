"""Execute every governed metric, reconcile against the KPI marts, and export values for the dashboard."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import duckdb
import yaml

DIM_KEYS = {"dim_geography": "geography_key", "dim_product": "product_id", "dim_customer": "customer_id"}


def load_spec(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def metric_sql(spec: dict, metric: dict, dim: str | None = None) -> str:
    expr = metric["expr"]
    if dim is None:
        return f"select {expr} as value from fct_order_items"
    d = spec["dimensions"][dim]
    if d["table"] == "fct_order_items":
        join, col = "", d["column"]
    elif d["table"] == "dim_date":
        join, col = "join dim_date d on d.date_key = fct_order_items.order_date", f"d.{d['column']}"
    else:
        join, col = f"join {d['table']} using ({DIM_KEYS[d['table']]})", d["column"]
    return f"select {col} as dim_value, {expr} as value from fct_order_items {join} group by 1 order by 1"


def run(db: str, spec_path: str, out_json: str) -> dict:
    spec = load_spec(spec_path)
    con = duckdb.connect(db, read_only=True)
    results, failures = [], []
    try:
        kd = con.execute("select sum(order_lines), sum(net_sales), sum(profit), sum(on_time_lines), sum(deliverable_lines), sum(late_lines) from kpi_daily").fetchone()
        expected = {"order_lines": kd[0], "net_sales": kd[1], "profit": kd[2],
                    "on_time_delivery_rate": kd[3] / kd[4], "late_delivery_rate": kd[5] / kd[4], "profit_margin": kd[2] / kd[1]}
        for m in spec["metrics"]:
            overall = con.execute(metric_sql(spec, m)).fetchone()[0]
            if overall is None or not math.isfinite(float(overall)):
                failures.append(f"{m['name']}: non-finite overall value {overall}")
            if m["name"] in expected and not math.isclose(float(overall), float(expected[m["name"]]), rel_tol=1e-9):
                failures.append(f"{m['name']}: {overall} != mart-derived {expected[m['name']]}")
            by_dim = {}
            for dim in ("market", "shipping_mode", "department_name", "customer_segment"):
                rows = con.execute(metric_sql(spec, m, dim)).fetchall()
                by_dim[dim] = [{"key": r[0], "value": None if r[1] is None else float(r[1])} for r in rows]
            monthly = [{"key": r[0], "value": None if r[1] is None else float(r[1])} for r in con.execute(metric_sql(spec, m, "year_month")).fetchall()]
            results.append({**{k: m[k] for k in ("name", "label", "description", "expr", "unit", "good_direction")},
                            "overall": float(overall), "by_dimension": by_dim, "monthly": monthly})
    finally:
        con.close()
    report = {"metrics_checked": len(results), "reconciled_against_marts": sorted(expected), "failures": failures, "metrics": results}
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(report, indent=1))
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/supplypulse.duckdb")
    p.add_argument("--spec", default="metrics/metrics.yml")
    p.add_argument("--out", default="site/data/metrics.json")
    a = p.parse_args()
    r = run(a.db, a.spec, a.out)
    print(f"metrics executed: {r['metrics_checked']}; reconciled to marts: {r['reconciled_against_marts']}")
    for m in r["metrics"]:
        print(f"  {m['name']:<26} {m['overall']:.4f} {m['unit']}")
    if r["failures"]:
        print("FAILURES:", *r["failures"], sep="\n  ")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

import numpy as np
import pandas as pd

from supplypulse.anomaly.detect import detect, injection_test, robust_z
from supplypulse.catalog.metrics_check import metric_sql

SPEC = {"dimensions": {
    "market": {"table": "dim_geography", "column": "market"},
    "year": {"table": "dim_date", "column": "year"},
    "shipping_mode": {"table": "fct_order_items", "column": "shipping_mode"},
}}


def test_robust_z_flat_series_uses_relative_floor():
    z = robust_z(pd.Series([100.0] * 30 + [130.0]))
    assert np.isfinite(z["z"].iloc[-1]) and z["z"].iloc[-1] >= 3.5


def test_detector_flags_spike_and_not_noise():
    rng = np.random.default_rng(1)
    base = 100 + rng.normal(0, 1, 60)
    df = pd.DataFrame({"week": pd.date_range("2016-01-04", periods=60, freq="7D")})
    for k in ("order_lines", "on_time_delivery_rate", "cancellation_rate", "suspected_fraud_rate", "profit_margin", "avg_delay_days"):
        df[k] = base
    df.loc[45, "order_lines"] = 200.0
    out = detect(df)
    assert set(out["kpi"]) == {"order_lines"} and out.loc[0, "week"] == str(df["week"].iloc[45].date())


def test_injection_recall_rises_with_size():
    rng = np.random.default_rng(2)
    s = pd.Series(100 + rng.normal(0, 3, 120))
    assert injection_test(s, 6.0)["recall"] > injection_test(s, 3.0)["recall"]


def test_metric_sql_joins_by_dimension_table():
    m = {"expr": "count(*)"}
    assert "join dim_geography using (geography_key)" in metric_sql(SPEC, m, "market")
    assert "dim_date d on d.date_key" in metric_sql(SPEC, m, "year")
    assert "join" not in metric_sql(SPEC, m, "shipping_mode")
    assert metric_sql(SPEC, m).endswith("from fct_order_items")

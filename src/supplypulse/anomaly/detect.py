"""Weekly KPI anomaly detection with a robust rolling z-score, validated by anomaly injection.

Detector: for each weekly KPI, compare the value to the median of the previous `window` weeks, scaled by
1.4826 * MAD with a relative floor (so near-constant series do not produce infinite z-scores).
A point is flagged when |z| >= threshold. Three or more consecutive flags are labelled a level shift.

Validation: inject synthetic spikes of known size into the clean series and measure recall, plus the
false-positive rate on points that were not touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

WINDOW = 26
MIN_HISTORY = 12
THRESHOLD = 3.5
REL_FLOOR = 0.02  # scale is at least 2% of the median level

KPIS = {
    "order_lines": ("Order lines", "up"),
    "on_time_delivery_rate": ("On-time delivery rate", "down"),
    "cancellation_rate": ("Cancellation rate", "up"),
    "suspected_fraud_rate": ("Suspected fraud rate", "up"),
    "profit_margin": ("Profit margin", "down"),
    "avg_delay_days": ("Average delay (days)", "up"),
}


def weekly_kpis(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    try:
        df = con.execute("""
            select d.week_start as week, count(*) as order_lines,
                   sum(f.is_on_time) * 1.0 / sum(1 - f.is_shipping_canceled) as on_time_delivery_rate,
                   avg(f.is_order_canceled) as cancellation_rate,
                   avg(f.is_suspected_fraud) as suspected_fraud_rate,
                   sum(f.profit) / nullif(sum(f.net_sales), 0) as profit_margin,
                   sum(f.delay_days) filter (where f.is_shipping_canceled = 0) * 1.0 / sum(1 - f.is_shipping_canceled) as avg_delay_days
            from fct_order_items f join dim_date d on d.date_key = f.order_date
            where f.order_date between date '2015-01-05' and date '2018-01-28'
            group by 1 order by 1
        """).df()
    finally:
        con.close()
    df["week"] = pd.to_datetime(df["week"])
    return df


def robust_z(s: pd.Series, window: int = WINDOW, min_history: int = MIN_HISTORY) -> pd.DataFrame:
    prev = s.shift(1)
    med = prev.rolling(window, min_periods=min_history).median()
    mad = prev.rolling(window, min_periods=min_history).apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True)
    scale = np.maximum(1.4826 * mad, REL_FLOOR * med.abs()).replace(0, np.nan)
    return pd.DataFrame({"expected": med, "scale": scale, "z": (s - med) / scale})


def detect(df: pd.DataFrame, threshold: float = THRESHOLD) -> pd.DataFrame:
    rows = []
    for k, (label, bad) in KPIS.items():
        r = robust_z(df[k])
        flag = r["z"].abs() >= threshold
        run = flag.astype(int).groupby((~flag).cumsum()).cumsum()  # consecutive-flag counter
        for i in np.flatnonzero(flag.to_numpy()):
            rows.append({
                "week": str(df["week"].iloc[i].date()), "kpi": k, "label": label,
                "value": float(df[k].iloc[i]), "expected": float(r["expected"].iloc[i]), "z": round(float(r["z"].iloc[i]), 2),
                "direction": "above" if r["z"].iloc[i] > 0 else "below",
                "type": "level_shift" if run.iloc[i] >= 3 or (i + 1 < len(df) and flag.iloc[i + 1] and run.iloc[i] >= 2) else "spike",
                "worse_when": bad,
            })
    return pd.DataFrame(rows)


def injection_test(series: pd.Series, sigmas: float, trials: int = 200, n_inject: int = 4, seed: int = 11) -> dict:
    """Inject +sigmas * (robust scale) spikes at random weeks; return recall and false-positive rate."""
    rng = np.random.default_rng(seed)
    series = series.astype(float)
    base = robust_z(series)
    eligible = np.flatnonzero(base["scale"].notna().to_numpy())
    hits = total = fp = clean = 0
    for _ in range(trials):
        idx = rng.choice(eligible[:-1], size=n_inject, replace=False)
        idx = idx[np.argsort(idx)]
        if np.any(np.diff(idx) < 3):  # keep injections apart so they do not distort each other's baseline
            continue
        s = series.copy()
        s.iloc[idx] = s.iloc[idx].to_numpy() + sigmas * base["scale"].iloc[idx].to_numpy()
        z = robust_z(s)["z"].abs()
        flagged = z >= THRESHOLD
        hits += int(flagged.iloc[idx].sum()); total += len(idx)
        mask = np.ones(len(s), dtype=bool); mask[idx] = False; mask &= z.notna().to_numpy()
        # points right after an injection are contaminated baselines; exclude them from the FP count
        for j in idx:
            mask[j + 1: j + 4] = False
        fp += int(flagged.to_numpy()[mask].sum()); clean += int(mask.sum())
    return {"injected_sigma": sigmas, "injections": total, "recall": round(hits / total, 3) if total else None,
            "false_positive_rate": round(fp / clean, 4) if clean else None}


def run(db: str, out_json: str, clean_until: str = "2017-10-02") -> dict:
    """`clean_until`: injection validation uses only weeks before the known level shift so that the real
    break does not contaminate the false-positive estimate."""
    df = weekly_kpis(db)
    alerts = detect(df)
    clean = df[df["week"] < pd.Timestamp(clean_until)].reset_index(drop=True)
    evals = {k: [injection_test(clean[k], s) for s in (3.0, 4.0, 6.0)] for k in KPIS}
    report = {
        "method": {"window_weeks": WINDOW, "min_history_weeks": MIN_HISTORY, "threshold": THRESHOLD,
                   "relative_scale_floor": REL_FLOOR, "statistic": "robust z = (x - rolling median) / max(1.4826*MAD, 2% of median)"},
        "weeks_scanned": int(len(df)),
        "injection_validation_weeks": int(len(clean)),
        "alerts": alerts.to_dict("records"),
        "alert_counts_by_kpi": alerts.groupby("kpi").size().to_dict() if len(alerts) else {},
        "injection_validation": evals,
        "weekly_kpis": [{"week": str(r.week.date()), **{k: round(float(getattr(r, k)), 5) for k in KPIS}} for r in df.itertuples()],
    }
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/supplypulse.duckdb")
    p.add_argument("--out", default="site/data/anomalies.json")
    a = p.parse_args()
    r = run(a.db, a.out)
    print("weeks scanned:", r["weeks_scanned"], "| alerts by KPI:", r["alert_counts_by_kpi"])
    for k, rows in r["injection_validation"].items():
        print(f"{k:<24}", " | ".join(f"{x['injected_sigma']:.0f}σ recall {x['recall']} FPR {x['false_positive_rate']}" for x in rows))
    for a_ in r["alerts"][:12]:
        print(a_["week"], a_["kpi"], a_["type"], a_["direction"], "z=", a_["z"])


if __name__ == "__main__":
    main()

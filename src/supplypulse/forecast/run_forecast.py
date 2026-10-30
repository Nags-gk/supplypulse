"""End-to-end demand forecasting: hierarchy backtest, structural-break analysis, conformal intervals,
cost of ignoring the break, and a post-break production forecast.

Hierarchy (target = weekly order lines):  TOTAL  >  MKT|<market>  >  <market>|<department>
Why a hierarchy: segment series are intermittent (many zero weeks then bursts), so accuracy is reported
at every level instead of assuming one level is forecastable.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, Naive

from supplypulse.forecast.data import drop_partial_boundary_weeks, find_break, load_weekly
from supplypulse.forecast.evaluate import conformal_interval, leaderboard, wape, wape_by_horizon
from supplypulse.forecast.models import FEATURES, build_direct_table, fit_lgbm, lgbm_cross_validation, stat_cross_validation

H = 8
STAT_MODELS = ["Naive", "SeasonalNaive", "AutoETS", "AutoTheta"]
LEVELS = ("TOTAL", "MARKET", "SEGMENT")


def level_of(uid: str) -> str:
    return "TOTAL" if uid == "TOTAL" else "MARKET" if uid.startswith("MKT|") else "SEGMENT"


def build_panel(seg: pd.DataFrame) -> pd.DataFrame:
    mkt = seg.groupby(["ds", "market"], as_index=False)["y"].sum().assign(unique_id=lambda d: "MKT|" + d["market"])
    tot = seg.groupby("ds", as_index=False)["y"].sum().assign(unique_id="TOTAL")
    panel = pd.concat([seg[["unique_id", "ds", "y"]], mkt[["unique_id", "ds", "y"]], tot[["unique_id", "ds", "y"]]], ignore_index=True)
    return panel.sort_values(["unique_id", "ds"]).reset_index(drop=True)


def bottom_up(lgb_seg: pd.DataFrame, seg_meta: pd.DataFrame) -> pd.DataFrame:
    d = lgb_seg.merge(seg_meta, on="unique_id")
    mk = d.groupby(["ds", "cutoff", "market"], as_index=False)["LightGBM"].sum().assign(unique_id=lambda x: "MKT|" + x["market"])
    tt = d.groupby(["ds", "cutoff"], as_index=False)["LightGBM"].sum().assign(unique_id="TOTAL")
    return pd.concat([lgb_seg, mk[["unique_id", "ds", "cutoff", "LightGBM"]], tt[["unique_id", "ds", "cutoff", "LightGBM"]]], ignore_index=True)


def order_date_bounds(db: str) -> tuple[str, str]:
    con = duckdb.connect(db, read_only=True)
    try:
        lo, hi = con.execute("select min(order_date), max(order_date) from fct_order_items").fetchone()
    finally:
        con.close()
    return str(lo), str(hi)


def break_profile(db: str, week: pd.Timestamp) -> dict:
    """Compare operating profile before and after the break week (descriptive, not causal)."""
    con = duckdb.connect(db, read_only=True)
    try:
        wk = str(week.date())
        prof = con.execute(f"""
            select case when order_date >= date '{wk}' then 'post' else 'pre' end as regime,
                   count(*) as lines,
                   sum(units) * 1.0 / count(*) as units_per_line,
                   avg(net_sales) as avg_line_net_sales,
                   count(distinct product_id) as distinct_products,
                   sum(is_late) * 1.0 / sum(1 - is_shipping_canceled) as late_rate,
                   avg(is_order_canceled) as cancel_rate,
                   avg(is_suspected_fraud) as fraud_rate
            from fct_order_items where order_date between date '2015-01-05' and date '2018-01-28' group by 1
        """).df().set_index("regime")
        mix = con.execute(f"""
            select case when f.order_date >= date '{wk}' then 'post' else 'pre' end as regime, p.department_name,
                   count(*) * 1.0 / sum(count(*)) over (partition by case when f.order_date >= date '{wk}' then 'post' else 'pre' end) as share
            from fct_order_items f join dim_product p using (product_id)
            where f.order_date between date '2015-01-05' and date '2018-01-28' group by 1, 2
        """).df()
    finally:
        con.close()
    top = {r: mix[mix.regime == r].sort_values("share", ascending=False).head(4)[["department_name", "share"]].round(3).to_dict("records") for r in ("pre", "post")}
    return {"metrics": {k: {c: round(float(v), 4) for c, v in prof.loc[k].items()} for k in prof.index}, "top_departments": top}


def post_break_check(pre_panel: pd.DataFrame, post_total: pd.DataFrame, lgb_total_pred: float | None) -> dict:
    """What does a model trained only on the old regime predict for the first weeks of the new one?"""
    sf = StatsForecast(models=[Naive(), AutoETS(season_length=52)], freq="W-MON", n_jobs=1)
    f = sf.forecast(df=pre_panel[pre_panel["unique_id"] == "TOTAL"][["unique_id", "ds", "y"]], h=H).reset_index()
    m = post_total.head(H).merge(f, on="ds", how="inner")
    out = {"weeks_checked": int(len(m))}
    for name in ("Naive", "AutoETS"):
        out[f"wape_{name.lower()}_trained_on_old_regime"] = wape(m["y"].to_numpy(), m[name].to_numpy())
        out[f"bias_pct_{name.lower()}"] = float((m[name] - m["y"]).sum() / m["y"].sum() * 100)
    return out


def post_break_backtest(post_total: pd.DataFrame) -> dict:
    d = post_total[["ds", "y"]].assign(unique_id="TOTAL")
    sf = StatsForecast(models=[Naive(), AutoETS(season_length=1)], freq="W-MON", n_jobs=1)
    cv = sf.cross_validation(df=d, h=4, n_windows=3, step_size=2).reset_index(drop=True)
    return {"training_weeks_at_first_cutoff": int(len(d) - 4 - 2 * 2), "windows": 3, "horizon_weeks": 4,
            "wape_naive": wape(cv["y"].to_numpy(), cv["Naive"].to_numpy()),
            "wape_autoets": wape(cv["y"].to_numpy(), cv["AutoETS"].to_numpy())}


def run(db: str, out_json: str, out_cv: str) -> dict:
    t0 = time.time()
    lo, hi = order_date_bounds(db)
    seg = drop_partial_boundary_weeks(load_weekly(db), lo, hi)
    panel_all = build_panel(seg)
    brk = find_break(panel_all[panel_all["unique_id"] == "TOTAL"].assign(market="", department=""))
    pre_seg, post_seg = seg[seg["ds"] < brk.week], seg[seg["ds"] >= brk.week]
    pre_panel, post_panel = build_panel(pre_seg), build_panel(post_seg)

    # series intermittency summary (why the hierarchy is evaluated at every level)
    zero_share = pre_panel.assign(level=pre_panel["unique_id"].map(level_of)).groupby("level")["y"].apply(lambda s: float((s == 0).mean()))
    cv_stat = stat_cross_validation(pre_panel, H, n_windows=8, step=4)
    cutoffs = [pd.Timestamp(c) for c in sorted(cv_stat["cutoff"].unique())]
    lgb = lgbm_cross_validation(pre_seg, cutoffs, H)
    meta = seg[["unique_id", "market"]].drop_duplicates()
    cv = cv_stat.merge(bottom_up(lgb, meta), on=["unique_id", "ds", "cutoff"], how="inner")
    cv["level"] = cv["unique_id"].map(level_of)
    # top-down reconciliation: rescale bottom-up LightGBM so segments/markets sum to the direct TOTAL forecast
    tot = cv[cv["unique_id"] == "TOTAL"][["ds", "cutoff", "AutoETS", "LightGBM"]].rename(columns={"AutoETS": "_tot_fc", "LightGBM": "_tot_lgb"})
    cv = cv.merge(tot, on=["ds", "cutoff"], how="left")
    cv["LightGBM_TD"] = cv["LightGBM"] * cv["_tot_fc"] / cv["_tot_lgb"].replace(0, np.nan)
    cv = cv.drop(columns=["_tot_fc", "_tot_lgb"])

    boards, champions, intervals, by_h = {}, {}, {}, {}
    for lvl in LEVELS:
        d = cv[cv["level"] == lvl].copy()
        best_stat = leaderboard(d, STAT_MODELS).iloc[0]["model"]
        d["Ensemble"] = (d["LightGBM_TD"] + d[best_stat]) / 2.0
        cv.loc[d.index, "Ensemble"] = d["Ensemble"]
        board = leaderboard(d, STAT_MODELS + ["LightGBM", "LightGBM_TD", "Ensemble"])
        boards[lvl] = board.round(4).to_dict("records")
        champions[lvl] = board.iloc[0]["model"]
        if lvl == "TOTAL":
            intervals[lvl] = conformal_interval(d, champions[lvl], level=0.8)
            by_h[lvl] = wape_by_horizon(d, champions[lvl]).round(4).to_dict("records")

    total_pre = pre_panel[pre_panel["unique_id"] == "TOTAL"]
    total_post = post_panel[post_panel["unique_id"] == "TOTAL"].sort_values("ds")
    cost = post_break_check(pre_panel, total_post, None)
    pb_test = post_break_backtest(total_post)

    sf = StatsForecast(models=[AutoETS(season_length=1)], freq="W-MON", n_jobs=1)
    f = sf.forecast(df=total_post[["unique_id", "ds", "y"]], h=H, level=[80]).reset_index().rename(
        columns={"AutoETS": "yhat", "AutoETS-lo-80": "lo80", "AutoETS-hi-80": "hi80"})
    for c in ("yhat", "lo80", "hi80"):
        f[c] = f[c].clip(lower=0)

    hist = panel_all[panel_all["unique_id"] == "TOTAL"]
    mkt_hist = panel_all[panel_all["unique_id"].str.startswith("MKT|")]
    report = {
        "target": "order_lines per week",
        "horizon_weeks": H,
        "data_window": {"first_week": str(seg["ds"].min().date()), "last_week": str(seg["ds"].max().date()),
                        "segment_series": int(seg["unique_id"].nunique())},
        "intermittency_zero_week_share_pre_break": {k: round(v, 3) for k, v in zero_share.items()},
        "structural_break": {"week": str(brk.week.date()), "mean_weekly_before": round(brk.mean_before, 1),
                             "mean_weekly_after": round(brk.mean_after, 1), "pct_change": round(brk.pct_change * 100, 1),
                             "post_break_weeks": int(total_post["ds"].nunique()),
                             "profile": break_profile(db, brk.week)},
        "backtest": {"windows": len(cutoffs), "cutoffs": [str(c.date()) for c in cutoffs], "horizon_weeks": H,
                     "leaderboard_by_level": boards, "champion_by_level": champions,
                     "wape_by_horizon_total_champion": by_h["TOTAL"]},
        "conformal_interval_total_champion": intervals["TOTAL"],
        "cost_of_ignoring_break": cost,
        "post_break_backtest": pb_test,
        "production_forecast": {
            "note": f"Total weekly order lines, non-seasonal AutoETS fitted on the {total_post['ds'].nunique()} post-break weeks only; low confidence.",
            "rows": [{"ds": str(r.ds.date()), "yhat": round(float(r.yhat), 1), "lo80": round(float(r.lo80), 1), "hi80": round(float(r.hi80), 1)} for r in f.itertuples()],
        },
        "history_total_weekly": [{"ds": str(r.ds.date()), "y": float(r.y)} for r in hist.itertuples()],
        "history_market_weekly": [{"ds": str(r.ds.date()), "market": r.unique_id[4:], "y": float(r.y)} for r in mkt_hist.itertuples()],
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(report, indent=2))
    Path(out_cv).parent.mkdir(parents=True, exist_ok=True)
    cv.to_parquet(out_cv, index=False)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/supplypulse.duckdb")
    p.add_argument("--out", default="site/data/forecast.json")
    p.add_argument("--cv-out", default="data/exports/cv_predictions.parquet")
    a = p.parse_args()
    r = run(a.db, a.out, a.cv_out)
    print("zero-week share (pre-break):", r["intermittency_zero_week_share_pre_break"])
    print("break:", {k: v for k, v in r["structural_break"].items() if k != "profile"})
    for lvl, rows in r["backtest"]["leaderboard_by_level"].items():
        print(f"\n[{lvl}] champion={r['backtest']['champion_by_level'][lvl]}")
        for x in rows:
            print(f"  {x['model']:<14} WAPE {x['wape']*100:6.2f}%  bias {x['bias_pct']:+7.2f}%")
    print("\nconformal (total, 80%):", r["conformal_interval_total_champion"])
    print("ignoring the break:", r["cost_of_ignoring_break"])
    print("post-break backtest:", r["post_break_backtest"])
    print("WAPE by horizon (total champion):", [(x["h"], round(x["wape"] * 100, 1)) for x in r["backtest"]["wape_by_horizon_total_champion"]])
    print("elapsed", r["elapsed_seconds"])


if __name__ == "__main__":
    main()

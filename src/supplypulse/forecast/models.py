"""Forecast models: classical (statsforecast) and a global LightGBM direct multi-horizon model.

LightGBM is trained on raw counts with a Tweedie objective because segment-level demand in this
dataset is intermittent (many zero weeks followed by bursts). Scaling targets by a trailing mean
breaks on such series, which an earlier version of this module demonstrated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, AutoTheta, Naive, SeasonalNaive

SEASON = 52
LAGS = (0, 1, 2, 3, 7, 12, 25)  # offsets back from the forecast origin
FEATURES = [f"lag{k}" for k in LAGS] + [
    "roll4", "roll13", "weeks_since_nonzero", "seas_lag", "seas_lag_avg3", "h", "woy_sin", "woy_cos", "market", "department",
]


def stat_cross_validation(panel: pd.DataFrame, h: int, n_windows: int, step: int) -> pd.DataFrame:
    models = [Naive(), SeasonalNaive(season_length=SEASON), AutoETS(season_length=SEASON), AutoTheta(season_length=SEASON)]
    sf = StatsForecast(models=models, freq="W-MON", n_jobs=-1)
    return sf.cross_validation(df=panel[["unique_id", "ds", "y"]], h=h, n_windows=n_windows, step_size=step).reset_index(drop=True)


def _weeks_since_nonzero(y: np.ndarray, t: int) -> float:
    for k in range(0, t + 1):
        if y[t - k] > 0:
            return float(k)
    return float(t + 1)


def build_direct_table(seg: pd.DataFrame, horizons: int) -> pd.DataFrame:
    """One row per (series, origin week, horizon). Features use only information at the origin."""
    cats = {v: i for i, v in enumerate(sorted(set(seg["market"]) | set(seg["department"])))}
    rows = []
    for uid, g in seg.groupby("unique_id"):
        g = g.sort_values("ds").reset_index(drop=True)
        y = g["y"].to_numpy(dtype=float)
        mk, dp = cats[g["market"].iloc[0]], cats[g["department"].iloc[0]]
        for t in range(12, len(g)):
            base = {f"lag{k}": y[t - k] if t - k >= 0 else np.nan for k in LAGS}
            base["roll4"] = y[max(0, t - 3): t + 1].mean()
            base["roll13"] = y[max(0, t - 12): t + 1].mean()
            base["weeks_since_nonzero"] = _weeks_since_nonzero(y, t)
            for h in range(1, horizons + 1):
                s = t + h - SEASON  # same week last year; known at the origin because h <= 52
                target_ds = g["ds"].iloc[t] + pd.Timedelta(weeks=h)
                woy = target_ds.isocalendar().week
                rows.append({
                    **base, "h": h, "unique_id": uid, "origin_ds": g["ds"].iloc[t], "ds": target_ds,
                    "seas_lag": y[s] if s >= 0 else np.nan,
                    "seas_lag_avg3": y[max(0, s - 1): s + 2].mean() if s - 1 >= 0 else np.nan,
                    "woy_sin": np.sin(2 * np.pi * woy / 52.0), "woy_cos": np.cos(2 * np.pi * woy / 52.0),
                    "market": mk, "department": dp, "y": y[t + h] if t + h < len(g) else np.nan,
                })
    return pd.DataFrame(rows)


def fit_lgbm(train: pd.DataFrame, seed: int = 7) -> LGBMRegressor:
    model = LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.2, n_estimators=300, learning_rate=0.04, num_leaves=15,
        min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
        random_state=seed, verbose=-1,
    )
    model.fit(train[FEATURES], train["y"], categorical_feature=["market", "department"])
    return model


def lgbm_cross_validation(seg: pd.DataFrame, cutoffs: list[pd.Timestamp], h: int) -> pd.DataFrame:
    """For each cutoff c: train on rows whose target week <= c, predict h weeks ahead from origin c."""
    table = build_direct_table(seg, h)
    out = []
    for c in cutoffs:
        train = table[(table["ds"] <= c) & table["y"].notna()]
        test = table[table["origin_ds"] == c]
        model = fit_lgbm(train)
        out.append(pd.DataFrame({"unique_id": test["unique_id"], "ds": test["ds"], "cutoff": c,
                                 "LightGBM": np.maximum(model.predict(test[FEATURES]), 0.0)}))
    return pd.concat(out, ignore_index=True)

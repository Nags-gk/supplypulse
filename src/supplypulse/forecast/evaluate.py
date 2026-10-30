"""Forecast accuracy metrics and split-conformal prediction intervals."""
from __future__ import annotations

import numpy as np
import pandas as pd


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    denom = np.abs(y).sum()
    return float(np.abs(y - yhat).sum() / denom) if denom else float("nan")


def leaderboard(cv: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """WAPE (volume-weighted) and signed bias over all backtest windows and horizons."""
    rows = [{
        "model": m,
        "wape": wape(cv["y"].to_numpy(), cv[m].to_numpy()),
        "bias_pct": float((cv[m] - cv["y"]).sum() / cv["y"].sum() * 100),
    } for m in models]
    return pd.DataFrame(rows).sort_values("wape").reset_index(drop=True)


def wape_by_horizon(cv: pd.DataFrame, model: str) -> pd.DataFrame:
    d = cv.copy()
    d["h"] = ((d["ds"] - d["cutoff"]).dt.days // 7).astype(int)
    out = [{"h": int(h), "wape": wape(g["y"].to_numpy(), g[model].to_numpy())} for h, g in d.groupby("h")]
    return pd.DataFrame(out)


def conformal_interval(cv: pd.DataFrame, model: str, level: float = 0.8) -> dict:
    """Split-conformal: calibrate the quantile of absolute errors on all but the last window, then
    measure empirical coverage on the last window (honest, out-of-sample coverage)."""
    d = cv.assign(err=(cv["y"] - cv[model]).abs())
    cutoffs = sorted(d["cutoff"].unique())
    calib, test = d[d["cutoff"] != cutoffs[-1]], d[d["cutoff"] == cutoffs[-1]]
    n = len(calib)
    q = float(np.quantile(calib["err"], min(1.0, np.ceil((n + 1) * level) / n)))
    return {"level": level, "abs_error_quantile": q, "calibration_points": int(n),
            "holdout_points": int(len(test)), "holdout_coverage": float((test["err"] <= q).mean())}

"""Load weekly demand from the warehouse, drop partial boundary weeks, detect the structural break."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd


def load_weekly(db_path: str, target: str = "order_lines") -> pd.DataFrame:
    """Weekly demand per market x department as (unique_id, ds, y, market, department)."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.sql(
            f"select week_start as ds, market, department_name as department, {target} as y from demand_weekly"
        ).df()
    finally:
        con.close()
    df["ds"] = pd.to_datetime(df["ds"])
    df["unique_id"] = df["market"] + "|" + df["department"]
    return df.sort_values(["unique_id", "ds"]).reset_index(drop=True)


def drop_partial_boundary_weeks(df: pd.DataFrame, first_order_date: str, last_order_date: str) -> pd.DataFrame:
    """The first and last calendar weeks only partly overlap the data window and understate demand."""
    first, last = pd.Timestamp(first_order_date), pd.Timestamp(last_order_date)
    keep_from = df["ds"].min()
    if first.weekday() != 0:  # data starts mid-week
        keep_from = first.normalize() + pd.Timedelta(days=7 - first.weekday())
    keep_to = df["ds"].max()
    if last.weekday() != 6:  # data ends mid-week
        keep_to = last.normalize() - pd.Timedelta(days=last.weekday() + 7)
    return df[(df["ds"] >= keep_from) & (df["ds"] <= keep_to)].reset_index(drop=True)


@dataclass(frozen=True)
class Break:
    week: pd.Timestamp          # first week of the new regime
    mean_before: float
    mean_after: float
    pct_change: float
    share_series_dropping: float  # share of series whose mean falls by more than 30%


def detect_level_break(total: pd.Series, min_segment: int = 8) -> tuple[int, float]:
    """Single change-point in the mean by least squares. Returns (index of first 'after' point, SSE gain)."""
    y = total.to_numpy(dtype=float)
    n = len(y)
    if n < 2 * min_segment:
        raise ValueError("series too short for change-point search")
    base = ((y - y.mean()) ** 2).sum()
    best_i, best_sse = None, np.inf
    for i in range(min_segment, n - min_segment + 1):
        sse = ((y[:i] - y[:i].mean()) ** 2).sum() + ((y[i:] - y[i:].mean()) ** 2).sum()
        if sse < best_sse:
            best_i, best_sse = i, sse
    return int(best_i), float(1 - best_sse / base)


def find_break(df: pd.DataFrame) -> Break:
    total = df.groupby("ds")["y"].sum().sort_index()
    idx, _ = detect_level_break(total)
    week = total.index[idx]
    before, after = total.iloc[:idx].mean(), total.iloc[idx:].mean()
    per_series = df.assign(post=df["ds"] >= week).groupby(["unique_id", "post"])["y"].mean().unstack()
    active = per_series[per_series[False] > 0]
    share = float(((active[True] / active[False]) < 0.7).mean())
    return Break(week, float(before), float(after), float(after / before - 1), share)

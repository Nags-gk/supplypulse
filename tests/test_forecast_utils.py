import numpy as np
import pandas as pd

from supplypulse.forecast.data import detect_level_break, find_break
from supplypulse.forecast.evaluate import conformal_interval, leaderboard, wape


def test_wape_known_value():
    assert wape(np.array([10, 10]), np.array([8, 13])) == 0.25


def test_level_break_found_at_true_index():
    rng = np.random.default_rng(0)
    y = np.r_[rng.normal(100, 2, 60), rng.normal(40, 2, 20)]
    idx, gain = detect_level_break(pd.Series(y))
    assert idx == 60 and gain > 0.9


def test_find_break_reports_drop():
    weeks = pd.date_range("2016-01-04", periods=60, freq="7D")
    y = np.r_[np.full(40, 100.0), np.full(20, 40.0)]
    df = pd.DataFrame({"unique_id": "a", "ds": weeks, "y": y})
    b = find_break(df)
    assert b.week == weeks[40] and abs(b.pct_change + 0.6) < 1e-9


def test_leaderboard_sorted_and_bias_signed():
    cv = pd.DataFrame({"y": [10.0, 10.0], "good": [10.0, 11.0], "low": [5.0, 5.0]})
    lb = leaderboard(cv, ["good", "low"])
    assert list(lb["model"]) == ["good", "low"] and lb.loc[1, "bias_pct"] == -50.0


def test_conformal_holdout_is_last_window_only():
    cutoffs = pd.to_datetime(["2016-01-01"] * 10 + ["2016-02-01"] * 4)
    cv = pd.DataFrame({"cutoff": cutoffs, "y": 10.0, "m": 10.0 + np.r_[np.arange(10), np.zeros(4)]})
    r = conformal_interval(cv, "m", 0.8)
    assert r["calibration_points"] == 10 and r["holdout_points"] == 4 and r["holdout_coverage"] == 1.0

"""ATTD Full7 的泵锚点与按时段合并的出院前 P5 边界。"""

import numpy as np
import pandas as pd

from cgm_library.studies.attd.full import clock_period_p5, full7_features
from cgm_library.timeline.groups import make_groups
from cgm_library.workflows.window import calculate_confirmed_window


def test_full7_pump_windows_and_day_night_p5_are_distinct():
    start = pd.Timestamp("2026-01-01 12:00", tz="Asia/Shanghai")
    discharge = start + pd.Timedelta(days=4)
    times = pd.date_range(start, periods=4 * 288, freq="5min")
    values = np.where((times.hour < 6), 5.0, 8.0)
    groups = make_groups(pd.DataFrame({"timestamp": times, "glucose_clean": values}), 5)
    windows = {
        "pump_d1": (start, start + pd.Timedelta(days=1)),
        "pump_d3": (start + pd.Timedelta(days=2), start + pd.Timedelta(days=3)),
        "pre72h": (discharge - pd.Timedelta(days=3), discharge),
    }
    rows = [
        calculate_confirmed_window(groups, left, right, window_name=name)[0]
        for name, (left, right) in windows.items()
    ]
    result = full7_features(groups, pd.DataFrame(rows), discharge)
    assert result["mean_pump_d1"] == result["mean_pump_d3_qc"]
    assert result["delta_mean_pump_d3_d1"] == 0
    assert result["day_p5_pre24h"] == 8
    assert result["night_p5_pre24h"] == 5
    assert result["night_pre24h_expected_points"] == 72
    assert result["day_pre24h_expected_points"] == 216


def test_night_p5_is_na_when_its_own_coverage_is_low():
    start = pd.Timestamp("2026-01-01", tz="Asia/Shanghai")
    times = pd.date_range(start, periods=288, freq="5min")
    values = np.full(288, 6.0)
    values[:50] = np.nan
    groups = make_groups(pd.DataFrame({"timestamp": times, "glucose_clean": values}), 5)
    night = clock_period_p5(groups, start, start + pd.Timedelta(days=1), period="night_00to06")
    day = clock_period_p5(groups, start, start + pd.Timedelta(days=1), period="day_06to24")
    assert np.isnan(night["P5"])
    assert day["P5"] == 6

"""研究窗口覆盖率必须同时约束正式数值和未发生事件的零值。"""

import numpy as np
import pandas as pd

from cgm_library.timeline.groups import make_groups
from cgm_library.windows.definitions import study_windows
from cgm_library.workflows.window import calculate_confirmed_window


def _groups(values):
    start = pd.Timestamp("2026-01-01 03:00", tz="Asia/Shanghai")
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=len(values), freq="5min"),
            "glucose_clean": values,
        }
    )
    return make_groups(raw, 5), start


def test_sufficient_window_has_zero_when_no_event():
    groups, start = _groups([6.0] * 12)
    row, events = calculate_confirmed_window(
        groups, start, start + pd.Timedelta(hours=1), window_name="synthetic_hour"
    )
    assert row["coverage_pct"] == 100
    assert row["MEAN"] == 6
    assert row["hypo_episode_lt3p9_n"] == 0
    assert events == []


def test_insufficient_window_retains_event_evidence_but_formal_result_is_na():
    groups, start = _groups(
        [6, 6, 2.8, 2.8, 2.8, 6, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
    )
    row, events = calculate_confirmed_window(
        groups, start, start + pd.Timedelta(hours=1), window_name="synthetic_hour"
    )
    assert row["coverage_pct"] == 50
    assert row["metric_reason"] == "COVERAGE_BELOW_THRESHOLD"
    assert np.isnan(row["MEAN"])
    assert np.isnan(row["hypo_episode_lt3p9_n"])
    assert {event["event_type"] for event in events} == {
        "hypo_episode_lt3p9",
        "level2_period_lt3p0",
    }
    assert all(not event["outcome_qualified"] for event in events)


def test_pump_d1_and_d3_keep_the_day_two_gap_and_source_precision():
    base = pd.Timestamp("2026-01-01 12:00", tz="Asia/Shanghai")
    windows = study_windows(
        base,
        base + pd.Timedelta(days=5),
        base,
        base + pd.Timedelta(days=4),
        base,
    )
    assert windows["pump_d1"] == (base, base + pd.Timedelta(hours=24))
    assert windows["pump_d3"] == (base + pd.Timedelta(hours=48), base + pd.Timedelta(hours=72))
    assert windows["pre72h"][1] == windows["inpatient"][1]

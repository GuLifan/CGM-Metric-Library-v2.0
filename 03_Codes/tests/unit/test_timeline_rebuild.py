"""新时间裁定的可手算合成案例，不使用任何患者曲线。"""

import numpy as np
import pandas as pd
import pytest

from cgm_library.timeline.groups import TimelineError, make_groups
from cgm_library.windows.coverage import window_view
from cgm_library.windows.definitions import night_intersections


def frame(times, values):
    return pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(times, tz="Asia/Shanghai"),
            "glucose_clean": values,
            "source_row": range(2, len(times) + 2),
        }
    )


def test_four_zero_one_valid_uses_value_at_group_start_time():
    observations = frame(
        [
            "2026-01-01 08:00:00",
            "2026-01-01 08:01:00",
            "2026-01-01 08:02:00",
            "2026-01-01 08:03:00",
            "2026-01-01 08:04:00",
            "2026-01-01 08:05:00",
        ],
        [np.nan, np.nan, np.nan, np.nan, 6.4, 7.0],
    )
    groups = make_groups(observations, source_interval_min=1)
    assert groups.glucose_clean.tolist() == [6.4, 7.0]
    assert groups.analysis_time.iloc[0] == pd.Timestamp("2026-01-01 08:00:00", tz="Asia/Shanghai")
    assert groups.first_valid_raw_time.iloc[0] == pd.Timestamp(
        "2026-01-01 08:04:00", tz="Asia/Shanghai"
    )
    assert groups.analysis_time.iloc[1] - groups.analysis_time.iloc[0] == pd.Timedelta(minutes=5)
    assert groups.slot_qc_reason.iloc[0] == "PARTIAL_SOURCE_GROUP"


def test_two_source_groups_with_raw_valid_times_in_same_wall_clock_slot():
    observations = frame(
        [
            "2026-01-01 12:51:40",
            "2026-01-01 12:52:40",
            "2026-01-01 12:53:40",
            "2026-01-01 12:54:40",
            "2026-01-01 12:55:40",
            "2026-01-01 12:56:40",
            "2026-01-01 12:58:54",
        ],
        [np.nan, np.nan, np.nan, np.nan, 6.4, np.nan, 6.8],
    )
    groups = make_groups(observations, source_interval_min=1)
    assert groups.first_valid_raw_time.dt.floor("5min").nunique() == 1
    assert groups.analysis_time.iloc[1] - groups.analysis_time.iloc[0] == pd.Timedelta(minutes=5)
    start = pd.Timestamp("2026-01-01 12:50", tz="Asia/Shanghai")
    _, qc = window_view(groups, start, start + pd.Timedelta(minutes=10))
    assert qc["expected_points"] == qc["valid_points"] == 2
    assert qc["valid_minutes"] == pytest.approx(8 + 20 / 60)
    assert qc["coverage_pct"] == pytest.approx(100 * 5 / 6)


def test_five_minute_source_collision_is_na_with_raw_evidence():
    observations = frame(["2026-01-01 08:00:31", "2026-01-01 08:04:51"], [6.1, 6.4])
    groups = make_groups(observations, source_interval_min=5)
    assert len(groups) == 1
    assert groups.slot_conflict_flag.iloc[0]
    assert pd.isna(groups.glucose_clean.iloc[0])
    assert groups.valid_source_n.iloc[0] == 2
    assert groups.slot_qc_reason.iloc[0] == "MULTIPLE_VALID_SOURCE_TIMES_NA"


def test_partial_night_uses_intersection_as_coverage_denominator():
    study_start = pd.Timestamp("2026-01-01 03:00", tz="Asia/Shanghai")
    study_end = pd.Timestamp("2026-01-01 06:00", tz="Asia/Shanghai")
    nights = night_intersections(study_start, study_end)
    assert len(nights) == 1
    assert nights[0][0] == study_start and nights[0][1] == study_end
    times = pd.date_range(study_start, periods=36, freq="5min")
    observations = frame(times, [6.0] * len(times))
    groups = make_groups(observations, source_interval_min=5)
    _, qc = window_view(groups, nights[0][0], nights[0][1])
    assert qc["expected_points"] == qc["valid_points"] == 36


def test_overfull_minute_group_stops_instead_of_averaging_six_values():
    times = pd.date_range("2026-01-01 08:00", periods=6, freq="30s", tz="Asia/Shanghai")
    with pytest.raises(TimelineError, match="多于五条"):
        make_groups(frame(times, [6.0] * 6), source_interval_min=1)


@pytest.mark.parametrize("seconds", [59, 60, 61])
def test_overfull_depends_on_slot_count(seconds):
    times = pd.date_range("2026-01-01 08:00", periods=6, freq=f"{seconds}s", tz="Asia/Shanghai")
    # 最后一条为缺测仍占一个不同时刻。
    data = frame(times, [6.0] * 5 + [np.nan])
    if seconds == 59:
        with pytest.raises(TimelineError, match=r"6 个不同时刻.*\[59, 59, 59, 59, 59\]"):
            make_groups(data, 1)
    else:
        assert make_groups(data, 1).source_n.tolist() == [5, 1]

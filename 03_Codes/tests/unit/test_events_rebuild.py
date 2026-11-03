"""基础事件门槛反例；最新延长事件边界另见test_meeting_rules。"""

import numpy as np
import pandas as pd
import pytest

from cgm_library.events.engine import CONFIRMED_RULES, confirmed_event_types, detect_events


def grid(values, start="2026-01-01 00:00"):
    times = pd.date_range(start, periods=len(values), freq="5min", tz="Asia/Shanghai")
    return pd.DataFrame({"group_start": times, "analysis_time": times, "glucose_clean": values})


def event_of_type(rows, kind):
    return [row for row in rows if row["event_type"] == kind]


@pytest.mark.parametrize("low_points,expected", [(3, 1), (2, 0)])
def test_exact_three_low_points_onset_and_two_insufficient(low_points, expected):
    data = grid([6.0, *([3.5] * low_points), 6.0, 6.0, 6.0])
    events = detect_events(
        data,
        data.group_start.iloc[0],
        data.group_start.iloc[-1] + pd.Timedelta(minutes=5),
        CONFIRMED_RULES[0],
    )
    assert len(events) == expected


def test_one_normal_point_does_not_recover_but_na_breaks_event():
    data = grid([6.0, 3.5, 3.5, 3.5, 6.0, 3.5, 3.5, 3.5, 6.0, 6.0, 6.0])
    start, end = data.group_start.iloc[0], data.group_start.iloc[-1] + pd.Timedelta(minutes=5)
    episodes = detect_events(data, start, end, CONFIRMED_RULES[0])
    assert len(episodes) == 1
    assert episodes[0]["event_end"] == data.group_start.iloc[8]
    data.loc[5, "glucose_clean"] = np.nan
    episodes = detect_events(data, start, end, CONFIRMED_RULES[0])
    assert len(episodes) == 1
    assert episodes[0]["right_censored"]


def test_cross_midnight_and_independent_partial_nights():
    data = grid([3.5] * 9, start="2026-01-01 23:50")
    start = data.group_start.iloc[0]
    end = data.group_start.iloc[-1] + pd.Timedelta(minutes=5)
    full = detect_events(data, start, end, CONFIRMED_RULES[0])
    assert len(full) == 1 and full[0]["event_start_period"] == "day"
    midnight = pd.Timestamp("2026-01-02 00:00", tz="Asia/Shanghai")
    night = detect_events(data, midnight, end, CONFIRMED_RULES[0])
    assert len(night) == 1 and night[0]["event_start"] == midnight
    morning = grid([3.5] * 6, start="2026-01-02 05:55")
    night_end = pd.Timestamp("2026-01-02 06:00", tz="Asia/Shanghai")
    assert detect_events(morning, morning.group_start.iloc[0], night_end, CONFIRMED_RULES[0]) == []


def test_level2_nested_and_high_requires_120_continuous_minutes():
    data = grid([6.0, 3.5, 2.8, 2.8, 2.8, 3.5, 3.5, 6.0, 6.0, 6.0])
    start, end = data.group_start.iloc[0], data.group_start.iloc[-1] + pd.Timedelta(minutes=5)
    events = confirmed_event_types(data, start, end)
    assert len(event_of_type(events, "hypo_episode_lt3p9")) == 1
    assert len(event_of_type(events, "level2_period_lt3p0")) == 1
    high = grid([6.0] + [14.0] * 24 + [6.0])
    end = high.group_start.iloc[-1] + pd.Timedelta(minutes=5)
    assert len(detect_events(high, high.group_start.iloc[0], end, CONFIRMED_RULES[2])) == 1
    high.loc[10, "glucose_clean"] = np.nan
    assert detect_events(high, high.group_start.iloc[0], end, CONFIRMED_RULES[2]) == []

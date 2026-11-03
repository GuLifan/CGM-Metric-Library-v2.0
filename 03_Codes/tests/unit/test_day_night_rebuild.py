"""夜窗边界按局部交集计覆盖，夜间事件在该子窗内独立重算。"""

import pandas as pd

from cgm_library.timeline.groups import make_groups
from cgm_library.workflows.periods import calculate_day_night_long


def test_truncated_night_03to06_uses_36_slots_and_its_own_events():
    start = pd.Timestamp("2026-01-02 03:00", tz="Asia/Shanghai")
    times = pd.date_range(start, periods=36, freq="5min")
    values = [6.0] * 36
    values[6:9] = [2.8] * 3
    groups = make_groups(pd.DataFrame({"timestamp": times, "glucose_clean": values}), 5)
    rows, events = calculate_day_night_long(
        groups, start, start + pd.Timedelta(hours=3), parent_window="post7d"
    )
    assert len(rows) == 1
    assert rows[0]["period"] == "night_00to06"
    assert rows[0]["expected_points"] == 36
    assert rows[0]["valid_points"] == 36
    assert rows[0]["night_nadir"] == 2.8
    assert rows[0]["night_nadir_time"] == start + pd.Timedelta(minutes=30)
    assert {event["event_type"] for event in events} == {
        "hypo_episode_lt3p9",
        "level2_period_lt3p0",
    }

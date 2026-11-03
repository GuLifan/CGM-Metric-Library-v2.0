"""在研究窗口交集内独立计算 00–06 夜窗与 06–24 日窗。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgm_library.workflows.window import calculate_confirmed_window


def day_night_periods(
    start: pd.Timestamp, end: pd.Timestamp
) -> list[tuple[str, str, pd.Timestamp, pd.Timestamp]]:
    """研究边界可截断子窗；任何子窗分母都只用实际交集。"""
    if end <= start:
        raise ValueError("日夜研究窗口边界无效")
    periods = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        for name, left_hour, right_hour in (("night_00to06", 0, 6), ("day_06to24", 6, 24)):
            left = max(start, day + pd.Timedelta(hours=left_hour))
            right = min(end, day + pd.Timedelta(hours=right_hour))
            if left < right:
                periods.append((name, day.date().isoformat(), left, right))
    return periods


def calculate_day_night_long(
    groups: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    parent_window: str,
    coverage_min_pct: float = 70,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """夜间事件在每个夜窗交集内重新识别，不能按全天事件起点筛选。"""
    rows: list[dict[str, object]] = []
    night_events: list[dict[str, object]] = []
    for period, date, left, right in day_night_periods(start, end):
        result, events = calculate_confirmed_window(
            groups,
            left,
            right,
            window_name=f"{parent_window}/{period}/{date}",
            coverage_min_pct=coverage_min_pct,
        )
        day = pd.Timestamp(date, tz=left.tz)
        full_left = day + pd.Timedelta(hours=0 if period == "night_00to06" else 6)
        full_right = day + pd.Timedelta(hours=6 if period == "night_00to06" else 24)
        result.update(
            {
                "parent_window": parent_window,
                "period": period,
                "date": date,
                "is_partial_period": left != full_left or right != full_right,
            }
        )
        if period == "night_00to06":
            view = groups.loc[groups.group_start.ge(left) & groups.group_start.lt(right)]
            valid = view.loc[view.glucose_clean.notna()]
            if result["sufficient_flag"] and not valid.empty:
                minimum = valid.glucose_clean.min()
                first = valid.loc[valid.glucose_clean.eq(minimum)].iloc[0]
                result["night_nadir"] = float(minimum)
                result["night_nadir_time"] = first.analysis_time
                result["night_nadir_group_start"] = first.group_start
                result["night_nadir_count"] = int(valid.glucose_clean.eq(minimum).sum())
            else:
                result["night_nadir"] = np.nan
                result["night_nadir_time"] = pd.NaT
                result["night_nadir_group_start"] = pd.NaT
                result["night_nadir_count"] = 0
            night_events.extend(events)
        rows.append(result)
    return rows, night_events

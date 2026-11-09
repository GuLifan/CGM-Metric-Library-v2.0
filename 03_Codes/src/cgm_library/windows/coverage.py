"""窗口组首归属与有效支持时长，见 DECISIONS_20261109。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

STEP = pd.Timedelta(minutes=5)
MINUTE_NS = 60_000_000_000


def slot_support(groups, start, end):
    """按规划时间配对槽起止，整数纳秒支持可精确裁到下一个槽或窗末。"""
    if end <= start:
        raise ValueError("窗口结束必须晚于开始")
    ticks = pd.DatetimeIndex(groups.group_start)
    if ticks.hasnans or not ticks.is_monotonic_increasing or ticks.has_duplicates:
        raise ValueError("规划槽须严格递增、唯一且非空时刻")
    left, right = ticks.searchsorted([start, end])
    view = groups.iloc[left:right].copy()
    starts = ticks[left:right].as_unit("ns").asi8
    stops = np.minimum(starts + STEP.value, end.value)
    if len(stops) > 1:
        stops[:-1] = np.minimum(stops[:-1], starts[1:])
    return view, starts, stops


def window_view(groups, start, end, threshold_pct=70):
    """点数作QC，覆盖率和范围分钟使用相同的槽支持向量。"""
    if not 0 <= threshold_pct <= 100:
        raise ValueError("覆盖率门槛必须在 0–100 之间")
    view, starts, stops = slot_support(groups, start, end)
    duration = stops - starts
    view["support_minutes"] = duration / MINUTE_NS
    valid = view.glucose_clean.notna().to_numpy()
    expected = math.ceil((end - start) / STEP)
    valid_n = int(valid.sum())
    if valid_n > expected:
        raise ValueError("有效组数大于规划分母")
    support_ns = int(duration[valid].sum())
    span = end.value - start.value
    # 同时包含窗首和窗末未覆盖部分，满覆盖的完整轨迹缺口为零。
    holes = np.r_[starts[valid], end.value] - np.r_[start.value, stops[valid]]
    coverage = 100 * support_ns / span
    return view, {
        "window_start": start,
        "window_end": end,
        "expected_points": expected,
        "valid_points": valid_n,
        "coverage_pct": coverage,
        "missing_points": expected - valid_n,
        "max_gap_min": float(holes.max() / MINUTE_NS),
        "valid_minutes": support_ns / MINUTE_NS,
        "window_minutes": span / MINUTE_NS,
        "sufficient_flag": coverage >= threshold_pct,
    }

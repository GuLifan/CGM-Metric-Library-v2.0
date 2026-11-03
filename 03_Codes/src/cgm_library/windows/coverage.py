"""窗口按来源组起点归属，覆盖分母来自完整规划窗口。"""

from __future__ import annotations

import math
from itertools import pairwise

import pandas as pd

STEP = pd.Timedelta(minutes=5)


def window_view(
    groups: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, threshold_pct: float = 70
) -> tuple[pd.DataFrame, dict[str, object]]:
    """同一规划组在窗口中只能计一次；不以实际首有效时刻重新归槽。"""
    if end <= start:
        raise ValueError("窗口结束必须晚于开始")
    if not 0 <= threshold_pct <= 100:
        raise ValueError("覆盖率门槛必须在 0–100 之间")
    if groups.group_start.duplicated().any():
        raise ValueError("五分钟来源组起点重复，覆盖分子不可确定")
    view = groups.loc[groups.group_start.ge(start) & groups.group_start.lt(end)].copy()
    expected = math.ceil((end - start) / STEP)
    valid = view.loc[view.glucose_clean.notna()]
    valid_n = len(valid)
    if valid_n > expected:
        raise ValueError("有效组数大于规划分母；不得截顶覆盖率")
    coverage = 100 * valid_n / expected
    boundaries = [start, *valid.group_start.sort_values().tolist(), end]
    max_gap_min = max((right - left).total_seconds() / 60 for left, right in pairwise(boundaries))
    qc = {
        "window_start": start,
        "window_end": end,
        "expected_points": expected,
        "valid_points": valid_n,
        "coverage_pct": coverage,
        "missing_points": expected - valid_n,
        "max_gap_min": max_gap_min,
        "valid_minutes": valid_n * 5,
        "window_minutes": (end - start).total_seconds() / 60,
        "sufficient_flag": coverage >= threshold_pct,
    }
    return view, qc

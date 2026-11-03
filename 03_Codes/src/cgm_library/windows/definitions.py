"""研究窗口与可截断夜窗的明确交集。"""

from __future__ import annotations

import pandas as pd


def study_windows(
    record_start: pd.Timestamp,
    record_end: pd.Timestamp,
    admission: pd.Timestamp,
    discharge: pd.Timestamp,
    pump_start: pd.Timestamp | None = None,
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """只构造已确认的研究边界；泵停止时间不限制 D1/D3。

    全记录边界由上游五分钟来源组给出；其他窗口不自动裁剪到 CGM 记录，
    这样缺失的前后时段仍进入覆盖率分母。
    """
    stamps = (record_start, record_end, admission, discharge)
    if any(item.tzinfo is None for item in stamps):
        raise ValueError("研究锚点必须先解释为北京时间")
    if record_end <= record_start or discharge <= admission:
        raise ValueError("CGM 全记录或住院期边界无效")
    windows = {
        "all_record": (record_start, record_end),
        "inpatient": (admission, discharge),
        "pre72h": (discharge - pd.Timedelta(hours=72), discharge),
        "pre24h": (discharge - pd.Timedelta(hours=24), discharge),
        "post7d": (discharge, discharge + pd.Timedelta(days=7)),
    }
    if pump_start is not None:
        if pump_start.tzinfo is None:
            raise ValueError("泵开始锚点必须先解释为北京时间")
        windows["pump_d1"] = (pump_start, pump_start + pd.Timedelta(hours=24))
        windows["pump_d3"] = (
            pump_start + pd.Timedelta(hours=48),
            pump_start + pd.Timedelta(hours=72),
        )
    return windows


def night_intersections(
    start: pd.Timestamp,
    end: pd.Timestamp,
    night_start_hour: int = 0,
    night_end_hour: int = 6,
) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    """返回每个夜窗与研究窗口的非空交集；覆盖分母由交集时长决定。"""
    if end <= start or not 0 <= night_start_hour < night_end_hour <= 24:
        raise ValueError("研究窗口或夜窗边界无效")
    nights = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        night_start = day + pd.Timedelta(hours=night_start_hour)
        night_end = day + pd.Timedelta(hours=night_end_hour)
        left, right = max(start, night_start), min(end, night_end)
        if left < right:
            nights.append((left, right, day.date().isoformat()))
    return nights

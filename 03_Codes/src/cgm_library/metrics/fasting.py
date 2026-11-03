"""住院期 06:00 病房空腹 CGM 代理；完整清晨与日级 4/6。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgm_library.windows.coverage import window_view


def fasting_values(
    groups: pd.DataFrame,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    inpatient_start: pd.Timestamp,
    inpatient_end: pd.Timestamp,
) -> list[dict[str, object]]:
    """全记录也只取完整位于住院期内的 05:45–06:15 清晨。"""
    start = max(window_start, inpatient_start)
    end = min(window_end, inpatient_end)
    if end <= start:
        return []
    rows = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        morning_start = day + pd.Timedelta(hours=5, minutes=45)
        morning_end = day + pd.Timedelta(hours=6, minutes=15)
        if morning_start < start or morning_end > end:
            continue
        view, qc = window_view(groups, morning_start, morning_end, threshold_pct=0)
        if qc["expected_points"] != 6:
            raise ValueError("FBS 每日规划槽分母必须为六")
        valid = view.glucose_clean.dropna()
        enough = qc["valid_points"] >= 4
        rows.append(
            {
                "date": day.date().isoformat(),
                "fasting_window_start": morning_start,
                "fasting_window_end": morning_end,
                "fasting_expected_points": 6,
                "fasting_valid_points": qc["valid_points"],
                "fasting_cgm_0600": float(valid.median()) if enough else np.nan,
                "fasting_reason": "" if enough else "FBS_LT4_OF6",
            }
        )
    return rows


def fasting_cv(records: list[dict[str, object]]) -> dict[str, float | int | str]:
    """至少两个合格住院清晨，以样本 SD 除以日代理均值。"""
    values = np.array([row["fasting_cgm_0600"] for row in records], dtype=float)
    values = values[np.isfinite(values)]
    enough = len(values) >= 2
    return {
        "fasting_cgm_0600_cv_pct": (
            float(values.std(ddof=1) / values.mean() * 100) if enough else np.nan
        ),
        "fasting_valid_days_n": len(values),
        "fasting_cv_reason": "" if enough else "LT2_VALID_DAYS",
    }

"""ADRR 每日风险极值：日级覆盖先判，再对合格日等权平均。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgm_library.metrics.core import risk_values
from cgm_library.windows.coverage import window_view


def adrr_by_day(
    groups: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    coverage_min_pct: float = 70,
) -> tuple[dict[str, float | int | str], list[dict[str, object]]]:
    """只计算窗口与各自然日的交集；每个日交集独立检查 70% 覆盖。"""
    if end <= start:
        raise ValueError("ADRR 窗口边界无效")
    days: list[dict[str, object]] = []
    accepted: list[float] = []
    complete_accepted: list[float] = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        day_start = max(start, day)
        day_end = min(end, day + pd.Timedelta(days=1))
        if day_start >= day_end:
            continue
        view, qc = window_view(groups, day_start, day_end, threshold_pct=coverage_min_pct)
        valid = view.glucose_clean.dropna().to_numpy(float)
        risk_ok = False
        daily = np.nan
        max_low = np.nan
        max_high = np.nan
        if qc["sufficient_flag"] and len(valid):
            low_risk, high_risk, domain = risk_values(valid)
            risk_ok = bool(domain.all())
            if risk_ok:
                max_low = float(low_risk.max())
                max_high = float(high_risk.max())
                daily = max_low + max_high
                accepted.append(daily)
                if day_start == day and day_end == day + pd.Timedelta(days=1):
                    complete_accepted.append(daily)
        days.append(
            {
                "date": day.date().isoformat(),
                "is_partial_day": not (day_start == day and day_end == day + pd.Timedelta(days=1)),
                "day_window_start": day_start,
                "day_window_end": day_end,
                **qc,
                "adrr_daily_max_low": max_low,
                "adrr_daily_max_high": max_high,
                "adrr_daily_sum": daily,
                "adrr_day_accepted": risk_ok,
                "adrr_day_reason": (
                    ""
                    if risk_ok
                    else (
                        "DAY_COVERAGE_BELOW_THRESHOLD"
                        if not qc["sufficient_flag"]
                        else "RISK_TRANSFORM_DOMAIN"
                    )
                ),
            }
        )
    return {
        "ADRR": float(np.mean(accepted)) if accepted else np.nan,
        "ADRR_complete_days": float(np.mean(complete_accepted)) if complete_accepted else np.nan,
        "adrr_complete_valid_days_n": len(complete_accepted),
        "adrr_complete_reason": "" if complete_accepted else "NO_VALID_COMPLETE_DAY",
        "adrr_partial_sensitivity_delta": (
            float(np.mean(accepted) - np.mean(complete_accepted))
            if accepted and complete_accepted
            else np.nan
        ),
        "adrr_valid_days_n": len(accepted),
        "adrr_day_windows_n": len(days),
        "adrr_reason": "" if accepted else "NO_VALID_DAY",
    }, days

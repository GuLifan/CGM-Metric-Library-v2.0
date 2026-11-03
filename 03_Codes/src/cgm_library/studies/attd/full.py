"""ATTD Full CGM 七项：泵 D1/D3、出院前 72h 与前 24h 日夜 P5。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgm_library.windows.coverage import window_view
from cgm_library.workflows.periods import day_night_periods


def clock_period_p5(
    groups: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    period: str,
    coverage_min_pct: float = 70,
) -> dict[str, float | int | str]:
    """跨自然日合并同一日/夜时段的原始五分钟值，P5 用 linear 插值。"""
    if period not in ("night_00to06", "day_06to24"):
        raise ValueError("日夜 P5 时段名称不合法")
    expected = 0
    valid = 0
    values: list[float] = []
    for name, _, left, right in day_night_periods(start, end):
        if name != period:
            continue
        view, qc = window_view(groups, left, right, threshold_pct=0)
        expected += int(qc["expected_points"])
        valid += int(qc["valid_points"])
        values.extend(view.glucose_clean.dropna().to_numpy(float))
    coverage = 100 * valid / expected if expected else np.nan
    sufficient = expected > 0 and coverage >= coverage_min_pct
    return {
        "P5": float(np.quantile(values, 0.05, method="linear")) if sufficient else np.nan,
        "expected_points": expected,
        "valid_points": valid,
        "coverage_pct": coverage,
        "reason": ""
        if sufficient
        else ("NO_PERIOD_IN_WINDOW" if not expected else "PERIOD_COVERAGE_BELOW_THRESHOLD"),
    }


def full7_features(
    groups: pd.DataFrame,
    window_rows: pd.DataFrame,
    discharge: pd.Timestamp,
    *,
    coverage_min_pct: float = 70,
) -> dict[str, float | int | str]:
    """泵 D3 仅用于变化量；泵停止时刻不参与 D1/D3 截断。"""
    by_name = window_rows.set_index("window_name")
    if not by_name.index.is_unique:
        raise ValueError("Full7 输入中同一研究窗口出现重复结果行")

    def get(name: str, key: str) -> float:
        if name not in by_name.index:
            return np.nan
        return float(by_name.loc[name, key])

    d1 = get("pump_d1", "MEAN")
    d3 = get("pump_d3", "MEAN")
    pre24_start = discharge - pd.Timedelta(hours=24)
    day = clock_period_p5(
        groups,
        pre24_start,
        discharge,
        period="day_06to24",
        coverage_min_pct=coverage_min_pct,
    )
    night = clock_period_p5(
        groups,
        pre24_start,
        discharge,
        period="night_00to06",
        coverage_min_pct=coverage_min_pct,
    )
    return {
        "mean_pump_d1": d1,
        "mean_pump_d3_qc": d3,
        "delta_mean_pump_d3_d1": d3 - d1 if np.isfinite(d1) and np.isfinite(d3) else np.nan,
        "mean_pre72h": get("pre72h", "MEAN"),
        "cv_pre72h_pct": get("pre72h", "CV_pct"),
        "lbgi_pre72h": get("pre72h", "LBGI"),
        "day_p5_pre24h": day["P5"],
        "night_p5_pre24h": night["P5"],
        "day_pre24h_expected_points": day["expected_points"],
        "day_pre24h_valid_points": day["valid_points"],
        "day_pre24h_coverage_pct": day["coverage_pct"],
        "day_p5_pre24h_reason": day["reason"],
        "night_pre24h_expected_points": night["expected_points"],
        "night_pre24h_valid_points": night["valid_points"],
        "night_pre24h_coverage_pct": night["coverage_pct"],
        "night_p5_pre24h_reason": night["reason"],
        "pump_d1d3_reason": ""
        if np.isfinite(d1) and np.isfinite(d3)
        else "PUMP_WINDOW_UNAVAILABLE",
    }

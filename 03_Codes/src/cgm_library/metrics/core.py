"""按 01.md 计算可独立验收的连续指标；MAGE 和事件另设闸门。"""

from __future__ import annotations

import numpy as np
import pandas as pd

INTERVAL_MIN = 5
RANGES = {"level2": 3.0, "hypo": 3.9, "tight_upper": 7.8, "upper": 10.0, "high": 13.9}
QUANTILES = (5, 25, 50, 75, 95)


def risk_values(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """标准 Kovatchev 变换；极小正值若超出数学定义域，显式返回不可算。"""
    mg_dl = np.asarray(values, dtype=float) * 18
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        score = 1.509 * (np.log(mg_dl) ** 1.084 - 5.381)
        risk = 10 * score**2
    return np.where(score < 0, risk, 0), np.where(score > 0, risk, 0), np.isfinite(score)


def gri_from_percentages(
    tbr2_pct: float, tbr1_pct: float, tar2_pct: float, tar1_pct: float
) -> dict[str, float]:
    """GRI 输入必须是 0–100 百分数；最终封顶 100。"""
    low = 3.0 * tbr2_pct + 2.4 * tbr1_pct
    high = 1.6 * tar2_pct + 0.8 * tar1_pct
    return {
        "GRI_raw": low + high,
        "GRI": min(low + high, 100.0),
        "hypoglycemia_component": low,
        "hyperglycemia_component": high,
    }


def pooled_metrics(values: np.ndarray | list[float]) -> dict[str, float | int | str | bool]:
    """单窗口五分钟有效点算术指标；覆盖门槛由调用方先判定。"""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if (x <= 0).any():
        raise ValueError("pooled_metrics 只能使用已清洗的有效正血糖值")
    numeric_keys = (
        "MEAN",
        "SD",
        "CV_pct",
        "cv_prop",
        "GMI",
        "LBGI",
        "HBGI",
        "LAGE",
        "TIR_pct",
        "TAR_pct",
        "TAR1_pct",
        "TAR2_pct",
        "TBR_pct",
        "TBR1_pct",
        "TBR2_pct",
        "TITR_pct",
        "time_7p8_10_pct",
        "GRI",
        "GRI_raw",
        "hypoglycemia_component",
        "hyperglycemia_component",
        "global_min",
        "P5",
        "P25",
        "P50",
        "P75",
        "P95",
        "TIR_minutes",
        "TAR_minutes",
        "TBR_minutes",
        "TITR_minutes",
        "valid_minutes",
    )
    if len(x) == 0:
        return {
            **dict.fromkeys(numeric_keys, np.nan),
            "min_value_qc_flag": "NO_VALID_GLUCOSE",
            "risk_transform_domain_flag": False,
        }
    mean = float(x.mean())
    sd = float(x.std(ddof=1)) if len(x) >= 2 else np.nan
    low_risk, high_risk, risk_domain = risk_values(x)
    result: dict[str, float | int | str | bool] = {
        "MEAN": mean,
        "SD": sd,
        "CV_pct": float(sd / mean * 100),
        "cv_prop": float(sd / mean),
        "GMI": 3.31 + 0.02392 * (mean * 18),
        "LBGI": float(low_risk.mean()) if risk_domain.all() else np.nan,
        "HBGI": float(high_risk.mean()) if risk_domain.all() else np.nan,
        "risk_transform_domain_flag": not bool(risk_domain.all()),
        "LAGE": float(x.max() - x.min()),
        "global_min": float(x.min()),
        "min_value_qc_flag": "BELOW_1P8_VALID" if x.min() < 1.8 else "OK",
        "valid_minutes": len(x) * INTERVAL_MIN,
    }
    conditions = {
        "TIR": (x >= RANGES["hypo"]) & (x <= RANGES["upper"]),
        "TAR": x > RANGES["upper"],
        "TAR1": (x > RANGES["upper"]) & (x <= RANGES["high"]),
        "TAR2": x > RANGES["high"],
        "TBR": x < RANGES["hypo"],
        "TBR1": (x >= RANGES["level2"]) & (x < RANGES["hypo"]),
        "TBR2": x < RANGES["level2"],
        "TITR": (x >= RANGES["hypo"]) & (x <= RANGES["tight_upper"]),
        "time_7p8_10": (x > RANGES["tight_upper"]) & (x <= RANGES["upper"]),
    }
    for name, mask in conditions.items():
        result[name + "_pct"] = float(mask.mean() * 100)
        if name in ("TIR", "TAR", "TBR", "TITR"):
            result[name + "_minutes"] = int(mask.sum()) * INTERVAL_MIN
    result.update(
        gri_from_percentages(
            result["TBR2_pct"], result["TBR1_pct"], result["TAR2_pct"], result["TAR1_pct"]
        )
    )
    result.update({f"P{q}": float(np.quantile(x, q / 100, method="linear")) for q in QUANTILES})
    return result


def modd(groups: pd.DataFrame) -> dict[str, float | int]:
    """相邻自然日同规划钟点配对；Day1 和 Day3 永不跨过缺失 Day2。"""
    valid = groups.loc[groups.glucose_clean.notna(), ["group_start", "glucose_clean"]]
    if valid.group_start.duplicated().any():
        raise ValueError("MODD 输入有重复规划槽，禁止静默平均或任取")
    lookup = dict(zip(valid.group_start, valid.glucose_clean, strict=True))
    pairs = [
        (time, abs(value - lookup[time - pd.Timedelta(days=1)]))
        for time, value in lookup.items()
        if time - pd.Timedelta(days=1) in lookup
    ]
    return {
        "MODD_mmol_L": float(np.mean([diff for _, diff in pairs])) if pairs else np.nan,
        "modd_matched_pairs_n": len(pairs),
        "modd_valid_day_pairs_n": len({time.date() for time, _ in pairs}),
    }

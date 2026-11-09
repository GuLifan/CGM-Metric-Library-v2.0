"""原始血糖保真清洗：无效值 NA，未标错的正低值保留，重复冲突不平均。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgm_library.contracts.schema import CalculationError

TIMEZONE = "Asia/Shanghai"
NORMAL_STATES = {"", "0", "ok", "normal", "正常"}
INVALID_STATES = {"error", "invalid", "错误", "无效"}


class RawEvidenceError(CalculationError):
    """文件计算已停止，仍可导出已完成的逐源行清洗证据。"""

    def __init__(self, code: str, message: str, evidence: pd.DataFrame) -> None:
        super().__init__(code, message)
        self.evidence = evidence


def clean_observations(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """返回逐源行证据、去重后的原始观测与文件级 QC，不修改读入表。"""
    required = {"raw_time", "glucose_raw", "source_row"}
    if raw.empty or not required.issubset(raw):
        raise CalculationError("ERROR03", "原始文件为空或缺少必要列")
    evidence = raw.copy().reset_index(drop=True)
    raw_time = evidence.raw_time.astype(str).str.strip()
    parsed = pd.to_datetime(raw_time, format="mixed", errors="coerce")
    try:
        parsed = (
            parsed.dt.tz_localize(TIMEZONE)
            if parsed.dt.tz is None
            else parsed.dt.tz_convert(TIMEZONE)
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise CalculationError("ERROR04", "时间戳混合时区或无法解释") from exc
    evidence["timestamp"] = parsed
    evidence["date_only_imputed"] = raw_time.str.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}").fillna(
        False
    )
    raw_value = evidence.glucose_raw.fillna("").astype(str).str.strip()
    numeric = pd.to_numeric(raw_value, errors="coerce").astype(float)
    if "source_unit" in evidence:
        unit = evidence.source_unit.astype(str)
        if (~unit.isin(["mmol/L", "mg/dL"])).any():
            raise CalculationError("ERROR05", "来源血糖单位未确认")
        numeric = numeric.where(unit.eq("mmol/L"), numeric / 18)
    states = (
        evidence.device_state.astype(str).str.strip().str.lower()
        if "device_state" in evidence
        else pd.Series("", index=evidence.index)
    )
    unknown_states = ~states.isin(NORMAL_STATES | INVALID_STATES)
    if unknown_states.any():
        raise CalculationError("ERROR06", "存在未确认的设备状态码，停止该文件计算")
    device_invalid = states.isin(INVALID_STATES)
    unknown_value = raw_value.ne("") & numeric.isna() & ~device_invalid
    if unknown_value.any():
        raise CalculationError("ERROR06", "存在未确认的非数值设备读数，停止该文件计算")
    evidence["glucose_numeric_mmol_L"] = numeric
    evidence["glucose_clean"] = numeric.where(
        np.isfinite(numeric) & numeric.gt(0) & ~device_invalid
    )
    evidence["below_1p8_flag"] = evidence.glucose_clean.gt(0) & evidence.glucose_clean.lt(1.8)
    evidence["duplicate_conflict_flag"] = False
    evidence["qc_reason"] = np.select(
        [
            parsed.isna(),
            device_invalid,
            numeric.le(0),
            numeric.isna() | ~np.isfinite(numeric),
            evidence.below_1p8_flag,
        ],
        [
            "TIMESTAMP_PARSE_ERROR",
            "DEVICE_INVALID",
            "NONPOSITIVE_INVALID",
            "MISSING_INVALID",
            "BELOW_1P8_VALID",
        ],
        default="OK",
    )
    evidence["raw_qc_reason"] = evidence["qc_reason"]
    valid_time = evidence.loc[evidence.timestamp.notna()].copy()
    if valid_time.empty:
        raise CalculationError("ERROR04", "所有原始时间戳均无法解析")
    duplicate_count = int(valid_time.timestamp.duplicated().sum())
    conflict_times = pd.DatetimeIndex([], tz=TIMEZONE)
    if duplicate_count:
        distinct = valid_time.groupby("timestamp").glucose_clean.nunique(dropna=True)
        conflict_times = distinct.loc[distinct.gt(1)].index
        conflict = evidence.timestamp.isin(conflict_times)
        evidence.loc[conflict, "duplicate_conflict_flag"] = True
        evidence.loc[conflict, "glucose_clean"] = np.nan
        evidence.loc[conflict, "qc_reason"] = "DUPLICATE_CONFLICT"
        # 冲突已置 NA，其余时刻至多一个不同的有效值。有效行优先，
        # 同值或全无效取源行号最小者，使导出的代表行可复核。
        valid_time = evidence.loc[evidence.timestamp.notna()].sort_values(
            ["timestamp", "glucose_clean", "source_row"], na_position="last"
        )
    else:
        valid_time = valid_time.sort_values("timestamp")
    evidence["is_representative"] = False
    selected = valid_time.drop_duplicates("timestamp").index
    evidence.loc[selected, "is_representative"] = True
    observations = evidence.loc[selected].reset_index(drop=True)
    qc = {
        "raw_points": len(evidence),
        "duplicate_count": duplicate_count,
        "duplicate_conflict_count": len(conflict_times),
        "invalid_value_count": int(evidence.glucose_clean.isna().sum()),
        "below_1p8_valid_count": int(evidence.below_1p8_flag.sum()),
        "zero_count": int(numeric.eq(0).sum()),
        "negative_count": int(numeric.lt(0).sum()),
        "unparseable_time_count": int(parsed.isna().sum()),
        "date_only_imputed_count": int(evidence.date_only_imputed.sum()),
        "device_invalid_count": int(device_invalid.sum()),
    }
    if observations.glucose_clean.notna().sum() == 0:
        raise RawEvidenceError("ERROR14", "该 CGM 文件没有有效正血糖读数", evidence)
    return evidence, observations, qc


def raw_interval_distribution(evidence: pd.DataFrame) -> list[dict[str, float | int]]:
    """原始时间排序后的相邻间隔频数，连同同时间重复的零秒一起保存。"""
    differences = evidence.timestamp.dropna().sort_values().diff().dt.total_seconds().dropna()
    counts = differences.value_counts().sort_index()
    return [
        {"interval_seconds": float(seconds), "adjacent_pairs_n": int(count)}
        for seconds, count in counts.items()
    ]

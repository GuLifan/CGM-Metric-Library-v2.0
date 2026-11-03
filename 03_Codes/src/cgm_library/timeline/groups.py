"""固定来源组的五分钟网格；组首负责窗口与一分钟源事件归属。"""

from __future__ import annotations

import numpy as np
import pandas as pd

STEP = pd.Timedelta(minutes=5)


class TimelineError(ValueError):
    """来源时间轴存在未获规则授权的歧义。"""


def make_groups(observations: pd.DataFrame, source_interval_min: int) -> pd.DataFrame:
    """把已经去重、清洗的原始读数映射到固定来源组。

    一分钟源的组起点取**首条原始记录**，之后每五分钟生成一组。
    组内只对有效正值求均值；代表时刻固定为组起点，哪怕组首是 0。
    首个有效原始时刻另存，不用于连续事件；Sparse 直接从上游原始观测取点。
    五分钟源同一组若有多个有效时刻，则整组 NA 并保存冲突证据。
    """
    if source_interval_min not in (1, 5):
        raise TimelineError("来源频率只能明确声明为 1 或 5 分钟")
    required = {"timestamp", "glucose_clean"}
    if observations.empty or not required.issubset(observations):
        raise TimelineError("来源观测为空或缺少时间/清洗值")
    data = observations.copy().sort_values("timestamp", kind="stable").reset_index(drop=True)
    if data.timestamp.isna().any() or data.timestamp.duplicated().any():
        raise TimelineError("原始时间为空或重复；须先经过重复冲突清洗")
    if not pd.api.types.is_datetime64_any_dtype(data.timestamp):
        raise TimelineError("timestamp 必须是已解析的日期时间")
    if "source_row" not in data:
        data["source_row"] = np.arange(2, len(data) + 2)
    numeric = pd.to_numeric(data.glucose_clean, errors="coerce")
    if numeric.notna().any() and (numeric.dropna() <= 0).any():
        raise TimelineError("glucose_clean 中有非正值；须先完成无效值清洗")
    data["glucose_clean"] = numeric
    origin = data.timestamp.iloc[0]
    data["group_index"] = ((data.timestamp - origin) // STEP).astype(int)
    counts = data.groupby("group_index", sort=True)
    max_index = int(data.group_index.max())
    index = pd.RangeIndex(0, max_index + 1, name="group_index")
    groups = pd.DataFrame(index=index)
    groups["group_start"] = pd.DatetimeIndex([origin + n * STEP for n in index])
    groups["group_end"] = groups.group_start + STEP
    groups["source_interval_min"] = source_interval_min
    groups["source_n"] = counts.size().reindex(index, fill_value=0).astype(int)
    groups["valid_source_n"] = counts.glucose_clean.count().reindex(index, fill_value=0).astype(int)
    groups["invalid_source_n"] = groups.source_n - groups.valid_source_n
    if source_interval_min == 1 and groups.source_n.gt(5).any():
        raise TimelineError("一分钟来源组内多于五条原始记录；需单独核查设备时钟")
    groups["glucose_clean"] = counts.glucose_clean.mean().reindex(index)
    valid = data.loc[data.glucose_clean.notna()]
    groups["first_valid_raw_time"] = valid.groupby("group_index").timestamp.first().reindex(index)
    groups["source_row_first"] = counts.source_row.min().reindex(index)
    groups["source_row_last"] = counts.source_row.max().reindex(index)
    groups["slot_conflict_flag"] = False
    if source_interval_min == 5:
        # 两个不同实际时刻的有效值落在同一规划组时整组 NA，不能平均或任取。
        groups["slot_conflict_flag"] = groups.valid_source_n.gt(1)
        groups.loc[groups.slot_conflict_flag, "glucose_clean"] = np.nan
        groups["analysis_time"] = groups.first_valid_raw_time
        groups.loc[groups.slot_conflict_flag, "analysis_time"] = pd.NaT
        groups["source_complete_flag"] = groups.valid_source_n.eq(1)
    else:
        # Lifan 2026-10-10 新裁定：事件也使用组首规则时间，原始时刻仅为 QC。
        groups["analysis_time"] = groups.group_start.where(groups.glucose_clean.notna())
        groups["source_complete_flag"] = groups.valid_source_n.eq(5)
    groups["slot_qc_reason"] = "OK"
    groups.loc[groups.source_n.eq(0), "slot_qc_reason"] = "MISSING_SLOT"
    groups.loc[groups.source_n.gt(0) & groups.valid_source_n.eq(0), "slot_qc_reason"] = (
        "INVALID_SLOT"
    )
    groups.loc[groups.glucose_clean.notna() & ~groups.source_complete_flag, "slot_qc_reason"] = (
        "PARTIAL_SOURCE_GROUP"
    )
    groups.loc[groups.slot_conflict_flag, "slot_qc_reason"] = "MULTIPLE_VALID_SOURCE_TIMES_NA"
    return groups.reset_index()

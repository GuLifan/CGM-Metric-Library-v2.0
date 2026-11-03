"""ATTD Sparse20：原始观测、固定钟点、所属窗口和唯一最近点。"""

from __future__ import annotations

import numpy as np
import pandas as pd

CLOCKS = ((6, 30), (11, 0), (17, 30), (22, 0))
TOLERANCE = pd.Timedelta(minutes=10)


def _windows(cgm_start: pd.Timestamp, discharge: pd.Timestamp):
    for day in range(3):
        start = discharge - pd.Timedelta(hours=72 - 24 * day)
        yield f"pre72h_d{day + 1}", start, start + pd.Timedelta(hours=24)
    yield "cgm_d1", cgm_start, cgm_start + pd.Timedelta(hours=24)
    yield (
        "cgm_d3",
        cgm_start + pd.Timedelta(hours=48),
        cgm_start + pd.Timedelta(hours=72),
    )


def extract_sparse20(
    raw_observations: pd.DataFrame, cgm_start: pd.Timestamp, discharge: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """严格从原始有效读数抽 20 个目标，不接受时间轴均值表。

    每个目标只在自己的 24 小时窗口、出院前和 ±10 分钟交集内找候选。
    保存全部合格候选；最近距离若并列，则目标记 NA 且不任意选值。
    """
    required = {"timestamp", "glucose_clean"}
    if not required.issubset(raw_observations) or "group_start" in raw_observations:
        raise ValueError("Sparse20 输入必须是有效原始观测，不得传入五分钟聚合表")
    if discharge <= cgm_start:
        raise ValueError("出院时刻必须晚于 CGM 首个有效原始时刻")
    valid = raw_observations.loc[raw_observations.glucose_clean.notna()].copy()
    valid = valid.sort_values("timestamp", kind="stable")
    if valid.empty or valid.timestamp.duplicated().any():
        raise ValueError("Sparse 原始观测为空或有未处理的重复时刻")
    if "source_row" not in valid:
        valid["source_row"] = valid.index + 2
    if (valid.glucose_clean <= 0).any():
        raise ValueError("Sparse 原始观测含非正清洗值")
    targets: list[dict] = []
    candidates: list[dict] = []
    for name, start, end in _windows(cgm_start, discharge):
        for hour, minute in CLOCKS:
            clock = f"{hour:02d}:{minute:02d}"
            target = start.normalize() + pd.Timedelta(hours=hour, minutes=minute)
            if target < start:
                target += pd.Timedelta(days=1)
            target_id = f"{name}_{hour:02d}{minute:02d}"
            record = {
                "target_id": target_id,
                "window_name": name,
                "window_start": start,
                "window_end": end,
                "clock": clock,
                "target_time": target,
                "actual_time": pd.NaT,
                "glucose": np.nan,
                "diff_min": np.nan,
                "matched_source_row": np.nan,
                "candidate_n": 0,
                "nearest_candidate_n": 0,
                "reason": "",
            }
            if target >= discharge:
                record["reason"] = "TARGET_AFTER_DISCHARGE"
                targets.append(record)
                continue
            eligible = valid.loc[
                valid.timestamp.ge(max(start, target - TOLERANCE))
                & valid.timestamp.lt(min(end, discharge))
                & valid.timestamp.le(target + TOLERANCE)
            ].copy()
            record["candidate_n"] = len(eligible)
            if eligible.empty:
                record["reason"] = "NO_VALID_RAW_CANDIDATE"
                targets.append(record)
                continue
            eligible["distance_min"] = (eligible.timestamp - target).abs().dt.total_seconds() / 60
            nearest_distance = eligible.distance_min.min()
            eligible["is_nearest"] = eligible.distance_min.eq(nearest_distance)
            record["nearest_candidate_n"] = int(eligible.is_nearest.sum())
            for point in eligible.itertuples():
                candidates.append(
                    {
                        "target_id": target_id,
                        "candidate_time": point.timestamp,
                        "glucose": point.glucose_clean,
                        "source_row": point.source_row,
                        "distance_min": point.distance_min,
                        "is_nearest": point.is_nearest,
                    }
                )
            if record["nearest_candidate_n"] != 1:
                record["reason"] = "TIED_NEAREST"
            else:
                point = eligible.loc[eligible.is_nearest].iloc[0]
                record.update(
                    {
                        "actual_time": point.timestamp,
                        "glucose": float(point.glucose_clean),
                        "diff_min": (point.timestamp - target).total_seconds() / 60,
                        "matched_source_row": point.source_row,
                        "reason": "MATCHED",
                    }
                )
            targets.append(record)
    return pd.DataFrame(targets), pd.DataFrame(
        candidates,
        columns=[
            "target_id",
            "candidate_time",
            "glucose",
            "source_row",
            "distance_min",
            "is_nearest",
        ],
    )

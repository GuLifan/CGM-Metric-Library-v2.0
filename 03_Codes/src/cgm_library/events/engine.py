"""不跨 NA/缺口的事件状态机；窗口归属使用来源组起点。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

SUPPORT = pd.Timedelta(minutes=5)


@dataclass(frozen=True)
class EventRule:
    event_type: str
    threshold: float
    minimum_min: float
    recovery_min: float
    high: bool = False


# 前三类为基础事件；延长事件从父事件及连续低值段关联派生。
CONFIRMED_RULES = (
    EventRule("hypo_episode_lt3p9", 3.9, 15, 15),
    EventRule("level2_period_lt3p0", 3.0, 15, 15),
    EventRule("prolonged_hyper_gt13p9_120", 13.9, 120, 0, True),
    EventRule("extended_hypo_lt3p9_120", 3.9, 120, 15),
    EventRule("prolonged_level2_lt3p0_120", 3.0, 120, 15),
)


def detect_events(
    groups: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    rule: EventRule,
    night_start_hour: int = 0,
    night_end_hour: int = 6,
) -> list[dict[str, object]]:
    """每个有效点最多支持随后五分钟，受下一点、NA、缺口和窗口末端裁剪。"""
    if end <= start:
        raise ValueError("事件窗口结束必须晚于开始")
    if groups.group_start.duplicated().any():
        raise ValueError("事件输入有重复规划槽")
    selected = groups.loc[groups.group_start.ge(start) & groups.group_start.lt(end)].copy()
    if selected.empty:
        return []
    # 一分钟来源 analysis_time 已由新裁定固定为组首；五分钟源保留其实际观测时间。
    selected["event_time"] = selected.analysis_time.fillna(selected.group_start)
    selected = selected.sort_values("event_time", kind="stable").reset_index(drop=True)
    if selected.event_time.duplicated().any():
        raise ValueError("事件时刻重复，不能任意排序")
    events: list[dict[str, object]] = []
    state: dict[str, object] | None = None
    previous_support_end: pd.Timestamp | None = None
    block_first = True

    def finish(boundary: pd.Timestamp, right_censored: bool, reason: str) -> None:
        nonlocal state
        if state is None:
            return
        if state["confirmed"] and state["max_continuous_low_min"] >= rule.minimum_min:
            event_start = state["start"]
            extreme = state["extreme"]
            extreme_time = state["extreme_time"]
            identity = f"{rule.event_type}|{event_start.isoformat()}|{start.isoformat()}"
            events.append(
                {
                    "event_id": hashlib.sha256(identity.encode()).hexdigest()[:20],
                    "event_type": rule.event_type,
                    "event_start": event_start,
                    "event_end": boundary,
                    "duration_min": (boundary - event_start).total_seconds() / 60,
                    "condition_minutes": state["condition_minutes"],
                    "max_continuous_condition_min": state["max_continuous_low_min"],
                    "nadir": np.nan if rule.high else extreme,
                    "peak": extreme if rule.high else np.nan,
                    "nadir_time": pd.NaT if rule.high else extreme_time,
                    "peak_time": extreme_time if rule.high else pd.NaT,
                    "left_censored": state["left_censored"],
                    "right_censored": right_censored,
                    "complete_event_flag": not (state["left_censored"] or right_censored),
                    "censor_reason": reason
                    if right_censored
                    else ("LEFT_UNKNOWN" if state["left_censored"] else ""),
                    "event_start_period": (
                        "night" if night_start_hour <= event_start.hour < night_end_hour else "day"
                    ),
                }
            )
        state = None

    for index, row in selected.iterrows():
        time = row.event_time
        if time >= end:
            break
        next_time = selected.event_time.iloc[index + 1] if index + 1 < len(selected) else end
        support_end = min(time + SUPPORT, next_time, end)
        duration_min = max(0.0, (support_end - time).total_seconds() / 60)
        if previous_support_end is not None and time > previous_support_end:
            finish(previous_support_end, True, "TIME_GAP")
            block_first = True
        value = row.glucose_clean
        if pd.isna(value) or duration_min <= 0:
            finish(time, True, "NA_OR_ZERO_SUPPORT")
            previous_support_end = support_end
            block_first = True
            continue
        value = float(value)
        if not np.isfinite(value):
            raise ValueError("事件输入含无法解释的非有限值")
        condition = value > rule.threshold if rule.high else value < rule.threshold
        if condition:
            if state is None:
                state = {
                    "start": time,
                    "left_censored": block_first,
                    "confirmed": False,
                    "continuous_low_min": 0.0,
                    "max_continuous_low_min": 0.0,
                    "condition_minutes": 0.0,
                    "recovery_min": 0.0,
                    "recovery_start": None,
                    "extreme": value,
                    "extreme_time": time,
                }
            state["continuous_low_min"] += duration_min
            state["max_continuous_low_min"] = max(
                state["max_continuous_low_min"], state["continuous_low_min"]
            )
            state["condition_minutes"] += duration_min
            state["recovery_min"] = 0.0
            state["recovery_start"] = None
            state["confirmed"] = (
                state["confirmed"] or state["continuous_low_min"] >= rule.minimum_min
            )
            if (value > state["extreme"]) if rule.high else (value < state["extreme"]):
                state["extreme"] = value
                state["extreme_time"] = time
        elif state is not None:
            state["continuous_low_min"] = 0.0
            if not state["confirmed"]:
                state = None
            elif rule.recovery_min == 0:
                finish(time, False, "")
            else:
                if state["recovery_start"] is None:
                    state["recovery_start"] = time
                state["recovery_min"] += duration_min
                if state["recovery_min"] >= rule.recovery_min:
                    finish(state["recovery_start"], False, "")
        block_first = False
        previous_support_end = support_end
    if state is not None and previous_support_end is not None:
        finish(previous_support_end, True, "WINDOW_OR_DEVICE_END")
    return events


def confirmed_event_types(
    groups: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict[str, object]]:
    """先识别父事件，再保存各连续120分钟子段，避免把一事件重复计数。"""
    import json

    events = [
        event for rule in CONFIRMED_RULES[:3] for event in detect_events(groups, start, end, rule)
    ]
    for rule, parent_type in zip(
        CONFIRMED_RULES[3:], ("hypo_episode_lt3p9", "level2_period_lt3p0")
    ):
        runs = detect_events(groups, start, end, EventRule(rule.event_type, rule.threshold, 120, 0))
        for parent in list(events):
            if parent["event_type"] != parent_type:
                continue
            children = [
                r
                for r in runs
                if parent["event_start"] <= r["event_start"]
                and r["event_end"] <= parent["event_end"]
            ]
            if not children:
                continue
            event = dict(parent)
            event.update(
                event_type=rule.event_type,
                event_id=hashlib.sha256(
                    (rule.event_type + str(parent["event_id"])).encode()
                ).hexdigest()[:20],
                parent_event_id=parent["event_id"],
                continuous_low_segments_n=len(children),
                continuous_low_segments_json=json.dumps(
                    [
                        {
                            "start": r["event_start"].isoformat(),
                            "end": r["event_end"].isoformat(),
                            "duration_min": r["duration_min"],
                        }
                        for r in children
                    ],
                    ensure_ascii=False,
                ),
            )
            events.append(event)
    return events

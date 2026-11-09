"""CGM 事件使用窗内规划支持时长，原始观测时间独立留证。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import pandas as pd

from cgm_library.windows.coverage import MINUTE_NS, slot_support


@dataclass(frozen=True)
class EventRule:
    event_type: str
    threshold: float
    minimum_min: float
    recovery_min: float
    high: bool = False
    parent_type: str | None = None


CONFIRMED_RULES = (
    EventRule("hypo_episode_lt3p9", 3.9, 15, 15),
    EventRule("level2_period_lt3p0", 3.0, 15, 15),
    EventRule("prolonged_hyper_gt13p9_120", 13.9, 120, 0, True),
    EventRule("extended_hypo_lt3p9_120", 3.9, 120, 15, parent_type="hypo_episode_lt3p9"),
    EventRule("prolonged_level2_lt3p0_120", 3.0, 120, 15, parent_type="level2_period_lt3p0"),
)


def _spans(mask):
    """布尔向量中每段连续真的半开下标区间。"""
    edges = np.flatnonzero(np.diff(mask, prepend=False, append=False))
    return zip(edges[::2], edges[1::2], strict=True)


def _scan(groups, start, end, rules, night_start=0, night_end=6):
    view, ticks, stops = slot_support(groups, start, end)
    values = view.glucose_clean.to_numpy(dtype=float)
    if np.isinf(values).any():
        raise ValueError("事件输入含非有限读数")
    observed = (
        view["first_valid_raw_time"]
        if "first_valid_raw_time" in view
        else view.get("analysis_time", view.group_start)
    ).to_numpy()

    def stamp(ns):
        return pd.Timestamp(int(ns), unit="ns", tz=start.tz)

    derived = {r.parent_type: r for r in rules if r.parent_type}
    base = [r for r in rules if not r.parent_type]
    if set(derived) - {r.event_type for r in base}:
        raise ValueError("事件规则缺少父类型")
    events = []
    # NA 和不相邻的规划槽都是硬边界。每个连续观测块独立检测各阈值。
    for a, b in _spans(np.isfinite(values)):
        cuts = np.r_[a, a + 1 + np.flatnonzero(ticks[a + 1 : b] != stops[a : b - 1]), b]
        for lo, hi in pairwise(cuts):
            terminal = (
                "WINDOW_OR_DEVICE_END"
                if hi == len(ticks)
                else (
                    "NA_OR_ZERO_SUPPORT"
                    if np.isnan(values[hi]) and ticks[hi] == stops[hi - 1]
                    else "TIME_GAP"
                )
            )
            for rule in base:
                mask = (
                    values[lo:hi] > rule.threshold if rule.high else values[lo:hi] < rule.threshold
                )
                runs = [(lo + l, lo + r) for l, r in _spans(mask)]
                j = 0
                while j < len(runs):
                    first, last = runs[j]
                    j += 1
                    first_len = int(stops[last - 1] - ticks[first])
                    if first_len < rule.minimum_min * MINUTE_NS:
                        continue
                    pieces = [(first, last, first_len)]
                    # 父事件确认后，短暂恢复不结束事件；这些恢复分钟不属于连续低值段。
                    while (
                        j < len(runs)
                        and ticks[runs[j][0]] - stops[last - 1] < rule.recovery_min * MINUTE_NS
                    ):
                        l, last = runs[j]
                        pieces.append((l, last, int(stops[last - 1] - ticks[l])))
                        j += 1
                    tail = int(stops[hi - 1] - stops[last - 1])
                    recovered = last < hi and tail >= rule.recovery_min * MINUTE_NS
                    boundary = stops[last - 1] if recovered else stops[hi - 1]
                    left_censored = first == lo
                    segment = values[first:last]
                    extreme = first + (np.argmax(segment) if rule.high else np.argmin(segment))
                    t0, te, tx = stamp(ticks[first]), stamp(boundary), stamp(ticks[extreme])
                    token = f"{rule.event_type}|{t0.isoformat()}|{start.isoformat()}"
                    parent = {
                        "event_id": hashlib.sha256(token.encode()).hexdigest()[:20],
                        "event_type": rule.event_type,
                        "event_start": t0,
                        "event_end": te,
                        "duration_min": (boundary - ticks[first]) / MINUTE_NS,
                        "condition_minutes": sum(p[2] for p in pieces) / MINUTE_NS,
                        "max_continuous_condition_min": max(p[2] for p in pieces) / MINUTE_NS,
                        "nadir": np.nan if rule.high else float(values[extreme]),
                        "peak": float(values[extreme]) if rule.high else np.nan,
                        "nadir_time": pd.NaT if rule.high else tx,
                        "peak_time": tx if rule.high else pd.NaT,
                        "first_observed_time": observed[first],
                        "extreme_observed_time": observed[extreme],
                        "left_censored": bool(left_censored),
                        "right_censored": not recovered,
                        "complete_event_flag": bool(recovered and not left_censored),
                        "censor_reason": terminal
                        if not recovered
                        else ("LEFT_UNKNOWN" if left_censored else ""),
                        "event_start_period": "night"
                        if night_start <= t0.hour < night_end
                        else "day",
                    }
                    events.append(parent)
                    child = derived.get(rule.event_type)
                    if child:
                        segments = [
                            {
                                "start": stamp(ticks[l]).isoformat(),
                                "end": stamp(stops[r - 1]).isoformat(),
                                "duration_min": n / MINUTE_NS,
                            }
                            for l, r, n in pieces
                            if n >= child.minimum_min * MINUTE_NS
                        ]
                        if segments:
                            identity = child.event_type + parent["event_id"]
                            events.append(
                                parent
                                | {
                                    "event_type": child.event_type,
                                    "event_id": hashlib.sha256(identity.encode()).hexdigest()[:20],
                                    "parent_event_id": parent["event_id"],
                                    "continuous_low_segments_n": len(segments),
                                    "continuous_low_segments_json": json.dumps(
                                        segments, ensure_ascii=False
                                    ),
                                }
                            )
    return events


def detect_events(groups, start, end, rule, night_start_hour=0, night_end_hour=6):
    """公开单规则入口，保留直接调用延长阈值规则的行为。"""
    from dataclasses import replace

    return _scan(
        groups, start, end, (replace(rule, parent_type=None),), night_start_hour, night_end_hour
    )


def confirmed_event_types(groups, start, end):
    return _scan(groups, start, end, CONFIRMED_RULES)

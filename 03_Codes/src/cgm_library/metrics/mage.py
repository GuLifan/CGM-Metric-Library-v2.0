"""Fernandes moving-average / Service MAGE的独立Python实现。

按论文的交叉区间、交替转折点、幅度积累和Service方向写成numpy流程。
本模块不调用R，也不向事件或Sparse提供插值。R iglu仅用于外部一致性验证。
参数固定5/32/45/180；mg/dL用于参考算法的1mg/dL低变异检查，输出回mmol/L。
"""

from itertools import pairwise

import numpy as np
import pandas as pd

DEFINITIONS = {"mmol_to_mg_dL": 18}
PARAMETERS = {"short_ma": 5, "long_ma": 32, "inter_gap": 45, "max_gap": 180}


def canonical_grid(times, values):
    valid = np.isfinite(values)
    times = pd.DatetimeIndex(times)[valid]
    values = np.asarray(values, float)[valid] * DEFINITIONS["mmol_to_mg_dL"]
    if len(values) < 2:
        return pd.DatetimeIndex([]), np.array([])
    # iglu的五分钟日网格以00:05开始，读数线性映射到钟点网格。
    origin = times[0].normalize()
    minutes = (times - origin).total_seconds().to_numpy() / 60
    first = max(5, int(np.ceil(minutes[0] / 5)) * 5)
    last = int(np.floor(minutes[-1] / 5)) * 5
    grid = np.arange(first, last + 0.1, 5, dtype=float)
    if not len(grid):
        return pd.DatetimeIndex([]), np.array([])
    y = np.interp(grid, minutes, values, left=np.nan, right=np.nan)
    for left, right in pairwise(minutes):
        if right - left > PARAMETERS["inter_gap"]:
            y[(grid > left) & (grid < right)] = np.nan
    return pd.DatetimeIndex(origin + pd.to_timedelta(grid, unit="min")), y


def trailing_average(x, width):
    # 首个完整窗口前保持该窗口均值；中间NA以该MA窗口有效读数均值计算。
    average = pd.Series(x).rolling(width, min_periods=1).mean().to_numpy(copy=True)
    initial = x[:width]
    average[:width] = np.nanmean(initial) if np.isfinite(initial).any() else np.nan
    return average


def turning_points(x):
    delta = trailing_average(x, PARAMETERS["short_ma"]) - trailing_average(x, PARAMETERS["long_ma"])
    crosses = [0]
    for i in range(1, len(x)):
        if not (
            np.isfinite(x[i])
            and np.isfinite(x[i - 1])
            and np.isfinite(delta[i])
            and np.isfinite(delta[i - 1])
        ):
            continue
        adjacent = delta[i] * delta[i - 1] < 0
        against_last = delta[i] * delta[crosses[-1]] < 0
        if adjacent or against_last:
            crosses.append(i)
    crosses.append(len(x) - 1)
    indices = []
    for a, b in pairwise(crosses):
        left = indices[-1] if indices else a
        interval = x[left : b + 1]
        if not np.isfinite(interval).any():
            continue
        offset = np.nanargmax(interval) if delta[a] > 0 else np.nanargmin(interval)
        indices.append(left + int(offset))
    return np.asarray(indices, dtype=int)


def directional_excursions(values, sd, ascending):
    """用幅度积累寻找两侧足够的大波动；尾部单侧合格波动仍保留。"""
    signed = values if ascending else -values
    anchor = 0
    cursor = 0
    pairs = []
    while cursor < len(values):
        earlier = signed[anchor : cursor + 1]
        valley = anchor + int(np.argmin(earlier))
        if signed[cursor] - signed[valley] <= sd:
            cursor += 1
            continue
        peak = cursor
        recovery = cursor
        for recovery in range(cursor, len(values)):
            if signed[recovery] > signed[peak]:
                peak = recovery
            if signed[peak] - signed[recovery] > sd or recovery == len(values) - 1:
                break
        pairs.append((valley, peak))
        if recovery == len(values) - 1:
            break
        # 下降方向保留已观察到的谷，以支持后续右侧幅度积累。
        anchor = recovery if ascending else peak
        cursor = recovery
    return pairs


def segment_mage(x, times, window_sd):
    base = {
        "start": times[0],
        "end": times[-1],
        "points_n": len(x),
        "mage": np.nan,
        "direction": None,
        "excursions": [],
        "reason": "",
    }
    finite = x[np.isfinite(x)]
    if len(x) < PARAMETERS["long_ma"] or len(finite) < 2:
        return base | {"reason": "SHORT_SEGMENT"}
    sd = window_sd  # mmol/L有效原值的全窗SD已换为mg/dL；各段共用。
    if sd < 1:
        return base | {"reason": "LOW_VARIATION"}
    indices = turning_points(x)
    values = x[indices]
    if len(values) < 2:
        return base | {"reason": "NO_EXCURSION"}
    plus = directional_excursions(values, sd, True)
    minus = directional_excursions(values, sd, False)
    if not plus and not minus:
        return base | {"reason": "NO_EXCURSION"}
    ascending = bool(plus) and (not minus or plus[0][1] <= minus[0][0])
    chosen = plus if ascending else minus
    amplitudes = [abs(values[b] - values[a]) for a, b in chosen]
    excursions = [
        {
            "start_index": int(indices[a]),
            "end_index": int(indices[b]),
            "amplitude_mmol_L": float(abs(values[b] - values[a]) / DEFINITIONS["mmol_to_mg_dL"]),
        }
        for a, b in chosen
    ]
    return base | {
        "mage": float(np.mean(amplitudes) / DEFINITIONS["mmol_to_mg_dL"]),
        "direction": "PLUS" if ascending else "MINUS",
        "excursions": excursions,
    }


def calculate_mage(times, values):
    time_index = pd.Index(times)
    if (
        len(time_index)
        and not pd.api.types.is_datetime64_any_dtype(time_index.dtype)
        and pd.api.types.infer_dtype(time_index, skipna=True) not in {"datetime", "datetime64"}
    ):
        raise ValueError("MAGE 需要已解析的时间向量")
    times = pd.DatetimeIndex(time_index)
    values = np.asarray(values, float)
    if values.ndim != 1 or len(times) != len(values):
        raise ValueError("MAGE 时间与血糖向量长度必须一致")
    if times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("MAGE 时间须有效、唯一且严格递增")
    if np.isinf(values).any() or (values <= 0).any():
        raise ValueError("MAGE 血糖仅接受有效正数或缺失")
    finite = values[np.isfinite(values)]
    window_sd = float(finite.std(ddof=1) * 18) if len(finite) >= 2 else np.nan
    grid, x = canonical_grid(times, values)
    if len(x) == 0:
        return {"value": np.nan, "reason": "SHORT_SERIES", "segments": []}
    missing = ~np.isfinite(x)
    edges = np.flatnonzero(np.diff(np.r_[False, missing, False]))
    qualifying = [
        (a, b) for a, b in zip(edges[::2], edges[1::2]) if (b - a) * 5 > PARAMETERS["max_gap"]
    ]
    partitions = []
    cursor = 0
    for a, b in qualifying:
        if cursor < a:
            partitions.append((cursor, a))
        partitions.append((a, b))
        cursor = b
    if cursor < len(x):
        partitions.append((cursor, len(x)))
    segments = []
    for a, b in partitions:
        if np.isfinite(x[a:b]).any():
            segments.append(segment_mage(x[a:b], grid[a:b], window_sd))
        else:
            segments.append(
                {
                    "start": grid[a],
                    "end": grid[b - 1],
                    "points_n": b - a,
                    "mage": np.nan,
                    "direction": None,
                    "excursions": [],
                    "reason": "GAP_SEGMENT",
                }
            )
    usable = [s for s in segments if np.isfinite(s["mage"])]
    if not usable:
        return {
            "value": np.nan,
            "reason": segments[0]["reason"] if len(segments) == 1 else "NO_VALID_SEGMENTS",
            "segments": segments,
        }
    weights = np.array([(s["end"] - s["start"]).total_seconds() / 300 for s in usable])
    value = float(np.average([s["mage"] for s in usable], weights=weights))
    return {"value": value, "reason": "", "segments": segments}

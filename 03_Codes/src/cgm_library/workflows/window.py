"""单个研究窗口的已确认指标与事件输出，统一使用覆盖率闸门。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cgm_library.events.engine import CONFIRMED_RULES, confirmed_event_types
from cgm_library.metrics.core import modd, pooled_metrics
from cgm_library.metrics.mage import calculate_mage
from cgm_library.windows.coverage import window_view


def calculate_confirmed_window(
    groups: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    window_name: str,
    coverage_min_pct: float = 70,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """共同覆盖分母下计算可独立验收的指标；MAGE参考未通过时仅输出候选值。

    覆盖不足的窗口仍保存已观察事件事实，但正式数值和事件次数为 NA。
    事件事实带 `outcome_qualified`，防止下游把证据行误作正式结局。
    """
    view, qc = window_view(groups, start, end, threshold_pct=coverage_min_pct)
    qualified = bool(qc["sufficient_flag"])
    if qualified:
        metrics = pooled_metrics(view.glucose_clean.to_numpy(), view.support_minutes)
        reason = ""
    else:
        metrics = pooled_metrics([])
        reason = "COVERAGE_BELOW_THRESHOLD"
    # MODD 配对数即使窗口不足也留给 QC；正式 MODD 数值仍受窗口覆盖闸门控制。
    modd_result = modd(view)
    if not qualified:
        modd_result["MODD_mmol_L"] = np.nan
    events = confirmed_event_types(groups, start, end)
    for event in events:
        event.update(
            {
                "window_name": window_name,
                "window_start": start,
                "window_end": end,
                "outcome_qualified": qualified,
            }
        )
    counts = {
        f"{rule.event_type}_n": (
            sum(event["event_type"] == rule.event_type for event in events) if qualified else np.nan
        )
        for rule in CONFIRMED_RULES
    }
    # 仅用普通父事件的nadir派生条件层级，不把延长/Level2重复算进去。
    for tenth in range(30, 39):
        n = sum(e["event_type"] == "hypo_episode_lt3p9" and e["nadir"] < tenth / 10 for e in events)
        prefix = f"hypo_cond_lt{tenth // 10}p{tenth % 10}"
        counts[prefix + "_n"] = n if qualified else np.nan
        counts[prefix + "_any"] = int(n > 0) if qualified else np.nan
    for rule in CONFIRMED_RULES:
        key = rule.event_type + "_n"
        counts[rule.event_type + "_any"] = int(counts[key] > 0) if qualified else np.nan
    row: dict[str, object] = {
        "window_name": window_name,
        "metric_reason": reason,
        **metrics,
        **qc,
        **modd_result,
        **counts,
    }
    # 候选结果可复核；R参考未完成时正式MAGE保持NA，避免误当已验收。
    mage = calculate_mage(view.group_start, view.glucose_clean.to_numpy()) if qualified else None
    row["MAGE"] = np.nan
    row["MAGE_candidate_mmol_L"] = mage["value"] if mage else np.nan
    row["mage_reason"] = "REFERENCE_NOT_VALIDATED" if qualified else reason
    row["mage_candidate_reason"] = mage["reason"] if mage else reason
    return row, events

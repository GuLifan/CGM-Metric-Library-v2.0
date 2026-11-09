"""单患者可复核计算；MAGE参考验收状态与其他指标分别记录。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cgm_library.contracts.fields import check_request_columns
from cgm_library.contracts.schema import CalculationError, RunConfig
from cgm_library.io.common import anchor_precision
from cgm_library.io.reader import locate_source, parse_anchor, read_cgm
from cgm_library.metrics.daily import adrr_by_day
from cgm_library.metrics.fasting import fasting_cv, fasting_values
from cgm_library.qc.raw import RawEvidenceError, clean_observations, raw_interval_distribution
from cgm_library.sampling.fixed_clock import extract_sparse20
from cgm_library.studies.attd.full import full7_features
from cgm_library.studies.attd.sparse import sparse_features
from cgm_library.timeline.groups import OverfullMinuteSlot, make_groups
from cgm_library.windows.definitions import study_windows
from cgm_library.workflows.periods import calculate_day_night_long
from cgm_library.workflows.window import calculate_confirmed_window


@dataclass(frozen=True)
class PatientPartialResult:
    """明确标记为部分成果，调用方不得将它当作甲方完整指标交付。"""

    status: str
    source_path: Path
    qc: dict[str, object]
    raw_evidence: pd.DataFrame
    raw_observations: pd.DataFrame
    raw_intervals: list[dict[str, float | int]]
    groups: pd.DataFrame
    window_rows: pd.DataFrame
    daily_risk_rows: pd.DataFrame
    day_night_rows: pd.DataFrame
    fasting_day_rows: pd.DataFrame
    event_rows: pd.DataFrame
    night_event_rows: pd.DataFrame
    sparse_targets: pd.DataFrame
    sparse_candidates: pd.DataFrame
    sparse5: dict[str, float | int | str]
    full7: dict[str, float | int | str]


def calculate_patient_partial(
    request_row: dict[str, str], config: RunConfig
) -> PatientPartialResult:
    """读取一个文件，沿共用 QC 后分成连续支线与原始 Sparse20 支线。

    `cgm_start` 已按 Lifan 本轮裁定取首个有效正血糖原始时刻。
    泵停止时间只作 QC，不限制 D1/D3。MAGE正式值仍需R参考验收；泵逆序只跳过泵指标。
    """
    check_request_columns(request_row, internal=True)
    source_path, source = locate_source(request_row, config)
    content = source_path.read_bytes()
    raw = read_cgm(source_path, source.unit, content=content)
    source_sha256 = hashlib.sha256(content).hexdigest()
    del content
    evidence, observations, raw_qc = clean_observations(raw)
    try:
        groups = make_groups(observations, source.interval_min)
    except OverfullMinuteSlot as exc:
        raise RawEvidenceError("ERROR05", str(exc), evidence) from exc
    first_raw_time = observations.timestamp.iloc[0]
    cgm_start = observations.loc[observations.glucose_clean.notna(), "timestamp"].iloc[0]
    admission = parse_anchor(request_row["入院日期"])
    discharge = parse_anchor(request_row["出院日期"])
    pump_text = str(request_row["胰岛素泵开始时间"]).strip()
    pump_start = parse_anchor(pump_text, pump_start=True) if pump_text else None
    pump_end_text = str(request_row["胰岛素泵停止时间"]).strip()
    pump_end = parse_anchor(pump_end_text) if pump_end_text else None
    pump_invalid = bool(pump_start is not None and pump_end is not None and pump_end <= pump_start)
    if discharge <= admission:
        raise CalculationError("ERROR04", "出院须晚于入院", "patient")
    windows = study_windows(
        groups.group_start.iloc[0],
        groups.group_end.iloc[-1],
        admission,
        discharge,
        None if pump_invalid else pump_start,
    )
    window_rows: list[dict[str, object]] = []
    daily_risk_rows: list[dict[str, object]] = []
    day_night_rows: list[dict[str, object]] = []
    fasting_day_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    night_event_rows: list[dict[str, object]] = []
    for name, (start, end) in windows.items():
        row, events = calculate_confirmed_window(
            groups, start, end, window_name=name, coverage_min_pct=config.coverage_pct
        )
        adrr_result, day_rows = adrr_by_day(
            groups, start, end, coverage_min_pct=config.coverage_pct
        )
        daily_risk_rows.extend(
            {"analysis_id": request_row["analysis_id"], "parent_window": name, **day}
            for day in day_rows
        )
        if not row["sufficient_flag"]:
            adrr_result["ADRR"] = float("nan")
            adrr_result["ADRR_complete_days"] = float("nan")
            adrr_result["adrr_partial_sensitivity_delta"] = float("nan")
            adrr_result["adrr_complete_reason"] = "WINDOW_COVERAGE_BELOW_THRESHOLD"
            adrr_result["adrr_reason"] = "WINDOW_COVERAGE_BELOW_THRESHOLD"
        row.update(adrr_result)
        periods, night_events = calculate_day_night_long(
            groups, start, end, parent_window=name, coverage_min_pct=config.coverage_pct
        )
        day_night_rows.extend({**request_row, **period} for period in periods)
        night_event_rows.extend({**request_row, **event} for event in night_events)
        morning_rows = fasting_values(
            groups,
            admission if name == "all_record" else start,
            discharge if name == "all_record" else end,
            admission,
            discharge,
        )
        fasting_day_rows.extend(
            {"analysis_id": request_row["analysis_id"], "window_name": name, **morning}
            for morning in morning_rows
        )
        fasting_result = fasting_cv(morning_rows)
        if not row["sufficient_flag"]:
            fasting_result["fasting_cgm_0600_cv_pct"] = float("nan")
            fasting_result["fasting_cv_reason"] = "WINDOW_COVERAGE_BELOW_THRESHOLD"
        row.update(fasting_result)
        # 甲方要求把请求表后续比对列复制到各结果行；入口已拒绝同名计算字段。
        window_rows.append({**request_row, **raw_qc, **row})
        event_rows.extend({**request_row, **event} for event in events)
    targets, candidates = extract_sparse20(observations, cgm_start, discharge)
    targets.insert(0, "analysis_id", request_row["analysis_id"])
    candidates.insert(0, "analysis_id", request_row["analysis_id"])
    window_frame = pd.DataFrame(window_rows)
    full7 = full7_features(groups, window_frame, discharge, coverage_min_pct=config.coverage_pct)
    if pump_invalid:
        for field in ("pump_d1d3_reason", "mean_pump_d1_reason", "delta_mean_pump_d3_d1_reason"):
            full7[field] = "PUMP_STOP_NOT_AFTER_START"
    qc = {
        **raw_qc,
        "analysis_id": request_row["analysis_id"],
        "source_sha256": source_sha256,
        "source_interval_min": source.interval_min,
        "source_unit": source.unit,
        "first_raw_time": first_raw_time,
        "cgm_start_first_valid_raw_time": cgm_start,
        "invalid_leading_unique_timestamps_n": int(observations.timestamp.lt(cgm_start).sum()),
        "pump_start_precision": anchor_precision(pump_text, pump_start=True),
        "pump_end_precision": anchor_precision(pump_end_text),
        "pump_start_parsed": pump_start,
        "pump_end_parsed": pump_end,
        "pump_end_missing": pump_end is None,
        "pump_end_not_after_start": bool(
            pump_start is not None and pump_end is not None and pump_end <= pump_start
        ),
        "pending_rule_gates": "MAGE_REFERENCE_VALIDATION",
        "pump_qc_reason": "PUMP_STOP_NOT_AFTER_START" if pump_invalid else "",
    }
    return PatientPartialResult(
        status="PARTIAL_RULE_GATED",
        source_path=source_path,
        qc=qc,
        raw_evidence=evidence,
        raw_observations=observations,
        raw_intervals=raw_interval_distribution(evidence),
        groups=groups,
        window_rows=window_frame,
        daily_risk_rows=pd.DataFrame(daily_risk_rows),
        day_night_rows=pd.DataFrame(day_night_rows),
        fasting_day_rows=pd.DataFrame(fasting_day_rows),
        event_rows=pd.DataFrame(event_rows),
        night_event_rows=pd.DataFrame(night_event_rows),
        sparse_targets=targets,
        sparse_candidates=candidates,
        sparse5=sparse_features(targets),
        full7=full7,
    )

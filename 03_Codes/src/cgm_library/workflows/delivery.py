"""Stream clinical details; derive every delivery table from the same patient calculation."""

from __future__ import annotations

import csv
import json
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache

import numpy as np
import pandas as pd

from cgm_library.contracts.fields import ASSETS
from cgm_library.io.pump_request import PUMP_PREFIX
from cgm_library.io.tables import four_places, write_csv, write_workbook
from cgm_library.studies.delivery import (
    EVENT_COLUMNS,
    PERIODS,
    PRE_DISCHARGE_SHEET,
    QC_COLUMNS,
    WINDOW_NAMES,
    after_day_columns,
    event_time_column,
    mode_columns,
    scalar_columns,
    summary_columns,
)
from cgm_library.studies.drq import GROUP_FILES

TEXT_COLUMNS = set(PUMP_PREFIX) | {
    "window_name",
    "period",
    "computation_status",
    "error_code",
    "error_message",
    "warning_codes",
    "metric_reason",
    "event_type",
    "censor_reason",
    "hypo_cond_thresholds",
    "device_link_basis",
    "source_folder",
    "pump_end_basis",
    "结果说明",
    "sparse_protocol",
}


def local_time(value):
    if value is None or value is pd.NaT:
        return ""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Shanghai")
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def is_time(column):
    return column.endswith(("window_start", "window_end", "nadir_time")) or column in {
        "event_start",
        "event_end",
    }


def display(column, value):
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if is_time(column):
        return local_time(value)
    if isinstance(value, (float, np.floating)):
        return four_places(value) if np.isfinite(value) else ""
    return value


def frame(records, columns):
    data = pd.DataFrame(records).reindex(columns=columns)
    for column in data:
        if is_time(column):
            data[column] = data[column].map(lambda v: local_time(v) if pd.notna(v) else "")
        elif column in TEXT_COLUMNS or column.endswith(("_reason", "_times")):
            data[column] = data[column].fillna("")
        elif column.endswith("flag"):
            data[column] = data[column].astype("boolean")
        else:
            data[column] = pd.to_numeric(data[column], errors="raise")
            if column.endswith(("_n", "_any")) or column in {
                "post_discharge_day",
                "窗口数",
                "合格窗口数",
                "sparse_d1_valid_n",
                "sparse_d3_valid_n",
                "sparse_pre72h_valid_n",
            }:
                data[column] = data[column].astype("Int64")
    return data


def _writer(stack, path, columns):
    stream = stack.enter_context(path.open("w", encoding="utf-8-sig", newline=""))
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    def emit(row):
        writer.writerow({k: display(k, row.get(k)) for k in columns})

    return emit


def _day_number(window):
    return (
        int(window.removeprefix("post_discharge_day_"))
        if window.startswith("post_discharge_day_")
        else None
    )


def add_event_times(record, window, values, *, include_nadir=True):
    """Use saved event facts and pre-rounding threshold membership, not rounded nadirs."""
    result = values.copy()
    evidence = record["audit"].get(window, {})
    for column in mode_columns(include_times=False):
        target = event_time_column(column)
        if target is None:
            continue
        count = values.get(column)
        if count is None or pd.isna(count):
            result[target] = None
            continue
        prefix, kind = column.rsplit("__", 1) if "__" in column else ("all", column)
        facts = evidence.get(
            {"all": "events", "night_00to06": "night_events", "day_06to24": "day_events"}[prefix],
            [],
        )
        kind = kind.removesuffix("_n")
        if kind.startswith("hypo_cond_lt"):
            threshold = f"3.{kind[-1]}"
            selected = [
                e
                for e in facts
                if e["event_type"] == "hypo_episode_lt3p9"
                and threshold in e.get("hypo_cond_thresholds", "").split("|")
            ]
        else:
            selected = [e for e in facts if e["event_type"] == kind]
        if len(selected) != int(count):
            raise ValueError(f"Saved event facts disagree with {window}/{column}")
        selected = sorted(selected, key=lambda e: (e["event_start"], e["event_end"]))
        result[target] = "; ".join(
            interval_text(e["event_start"], e["event_end"], e["nadir"] if include_nadir else None)
            for e in selected
        )
    return result


@lru_cache(maxsize=65536)
def interval_text(start, end, nadir=None):
    text = f"{local_time(start)} - {local_time(end)}"
    return text if nadir is None else f"{text} = {four_places(nadir)}"


def followup_sheet_row(record, request, day):
    """Day 0 displays saved pre24h; days 1–14 retain discharge-anchored follow-up."""
    from cgm_library.contracts.schema import CalculationError
    from cgm_library.io.reader import parse_anchor

    name = "pre24h" if day == 0 else f"post_discharge_day_{day}"
    values = record["tables"].get(name)
    if values is not None:
        return values | {
            "post_discharge_day": day or None,
            "computation_status": record["computation_status"],
        }
    try:
        start = parse_anchor(request["出院日期"]) + pd.Timedelta(days=day - 1)
        end = start + pd.Timedelta(days=1)
    except CalculationError:
        start = end = None
    computed = record["computation_status"] == "COMPUTED"
    row = {
        "post_discharge_day": day or None,
        "window_start": start,
        "window_end": end,
        "computation_status": record["computation_status"],
        "sufficient_flag": False,
        "valid_minutes": 0.0 if computed else None,
        "coverage_pct": 0.0 if computed else None,
        "metric_reason": "NO_RECORDING_IN_WINDOW" if computed else record["error_code"],
    }
    for period in PERIODS:
        row[period + "__coverage_pct"] = 0.0 if computed else None
        row[period + "__sufficient_flag"] = False
    return row


def _overview(record, identity):
    row = identity | {
        k: record.get(k, "")
        for k in (
            "computation_status",
            "error_code",
            "error_message",
            "warning_codes",
            "source_folder",
        )
    }
    row["device_link_basis"] = "REQUEST_DEVICE_FILENAME" if identity["设备文件名"] else "MISSING"
    row["pump_end_basis"] = "REQUEST" if identity["胰岛素泵停止时间"] else "MISSING"
    row["窗口数"] = sum(w in record["tables"] for w in WINDOW_NAMES)
    row["合格窗口数"] = sum(
        bool(record["tables"].get(w, {}).get("sufficient_flag")) for w in WINDOW_NAMES
    )
    row["结果说明"] = (
        "计算完成；各窗口独立判断覆盖率"
        if record["computation_status"] == "COMPUTED"
        else record["error_message"]
    )
    for window in WINDOW_NAMES:
        row.update({f"{window}_{k}": v for k, v in record["tables"].get(window, {}).items()})
    return row


def _events(record, window, row, identity):
    audit = record["audit"].get(window, {})
    for period, key, enough in [
        ("all", "events", row.get("sufficient_flag", False)),
        (PERIODS[0], "night_events", row.get(f"{PERIODS[0]}__sufficient_flag", False)),
        (PERIODS[1], "day_events", row.get(f"{PERIODS[1]}__sufficient_flag", False)),
    ]:
        if not enough:
            continue
        for event in audit.get(key, []):
            if event["event_type"] == "prolonged_hyper_gt13p9_120":
                continue
            yield (
                identity
                | {
                    "window_name": window,
                    "post_discharge_day": _day_number(window),
                    "period": period,
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                    **event,
                    "nadir_mmol_L": event["nadir"],
                }
                | {
                    "window_name": window,
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                }
            )


def export_delivery(root, request, prefix, *, audit_root=None):
    """Keep only compact scalar rows in memory; event details stream patient by patient."""
    out = root / "results"
    out.mkdir(exist_ok=True)
    audit_root = audit_root or root / "audit"
    grouped = {name: [] for name in GROUP_FILES}
    daily = {n: [] for n in range(1, 15)}
    followup_daily = {n: [] for n in range(15)}
    fbs, statuses, overview, scalars, full, sparse = [], [], [], [], [], []
    counts = Counter()
    with ExitStack() as stack:
        after = _writer(
            stack, out / f"{prefix}_AfterDischarge_Daily_Results.csv", after_day_columns()
        )
        events = _writer(stack, out / f"{prefix}_Hypoglycemia_Events.csv", EVENT_COLUMNS)
        qc = _writer(stack, out / f"{prefix}_Window_Quality.csv", QC_COLUMNS)
        for index, req in enumerate(request.to_dict("records"), 1):
            record = json.loads(
                (audit_root / f"request_{index:04d}.json").read_text(encoding="utf-8")
            )
            if record["request"] != req:
                raise ValueError(f"Request order or identity changed at row {index}")
            record["tables"] = {
                name: add_event_times(record, name, values)
                for name, values in record["tables"].items()
            }
            identity = {k: req[k] for k in PUMP_PREFIX}
            status = identity | {
                k: record.get(k, "")
                for k in (
                    "computation_status",
                    "error_code",
                    "error_message",
                    "warning_codes",
                )
            }
            statuses.append(status)
            overview.append(_overview(record, identity))
            row = identity.copy()
            for window in WINDOW_NAMES:
                row.update(
                    {f"{window}__{k}": v for k, v in record["tables"].get(window, {}).items()}
                )
            features = record.get("features", {})
            for key, label in (("full7", "Full7"), ("sparse5", "Sparse5")):
                row.update({f"{label}__{k}": v for k, v in features.get(key, {}).items()})
            scalars.append(row)
            if record["computation_status"] == "COMPUTED":
                full.append(identity | features["full7"])
                sparse.append(identity | features["sparse5"])
            for window, output_rows in grouped.items():
                output_rows.append(identity | record["tables"].get(window, {}))
            for n, output_rows in daily.items():
                output_rows.append(identity | record["tables"].get(f"cgm_day_{n}", {}))
            for n, output_rows in followup_daily.items():
                output_rows.append(identity | followup_sheet_row(record, req, n))
            fbs.append(identity | record["fbs"])
            # Even patient-level failures retain D1-D7 with their actual discharge anchor.
            windows = record["tables"].copy()
            if not windows:
                from cgm_library.contracts.schema import CalculationError
                from cgm_library.io.reader import parse_anchor
                from cgm_library.studies.drq import post_discharge_windows

                try:
                    discharge = parse_anchor(req["出院日期"])
                    anchors = post_discharge_windows(discharge, discharge)
                except CalculationError:
                    anchors = {f"post_discharge_day_{n}": (None, None) for n in range(1, 8)}
                windows = {
                    k: {
                        "window_start": a,
                        "window_end": b,
                        "sufficient_flag": False,
                        "metric_reason": record["error_code"],
                    }
                    for k, (a, b) in anchors.items()
                }
            for window, values in windows.items():
                base = (
                    identity
                    | values
                    | {
                        "window_name": window,
                        "post_discharge_day": _day_number(window),
                        "computation_status": record["computation_status"],
                    }
                )
                if _day_number(window):
                    after(base)
                    counts["after_discharge_rows"] += 1
                    counts["after_discharge_qualified_rows"] += bool(values.get("sufficient_flag"))
                    counts["maximum_post_discharge_day"] = max(
                        counts["maximum_post_discharge_day"], _day_number(window)
                    )
                for period in ("all", *PERIODS):
                    head = "" if period == "all" else period + "__"
                    qualified = values.get(head + "sufficient_flag", False)
                    qc(
                        base
                        | {
                            "period": period,
                            "coverage_pct": values.get(head + "coverage_pct"),
                            "sufficient_flag": qualified,
                            "metric_reason": ""
                            if qualified
                            else (
                                record["error_code"]
                                or record["audit"].get(window, {}).get("reason")
                                or "COVERAGE_BELOW_THRESHOLD"
                            ),
                        }
                    )
                for event in _events(record, window, values, identity):
                    events(event)
                    counts["hypoglycemia_event_rows"] += 1
    for window, suffix in GROUP_FILES.items():
        write_csv(frame(grouped[window], mode_columns()), out / f"{prefix}_{suffix}")
    write_workbook(
        out / f"{prefix}_Mode0_Daily_D1-14.xlsx",
        (
            (f"Day {n}", frame(rows, mode_columns() + ["MODD_vs_previous_cgm_day_mmol_L"]))
            for n, rows in daily.items()
        ),
    )
    write_workbook(
        out / f"{prefix}_AfterDischarge_Daily_D1-14.xlsx",
        (
            (PRE_DISCHARGE_SHEET if n == 0 else f"Day {n}", frame(rows, after_day_columns()))
            for n, rows in followup_daily.items()
        ),
    )
    counts["after_discharge_workbook_rows"] = len(request) * 15
    counts["after_discharge_workbook_sheets"] = 15
    counts["pre_discharge_workbook_rows"] = len(request)
    counts["event_time_column_pairs_per_mode"] = sum(
        event_time_column(c) is not None for c in mode_columns(include_times=False)
    )
    write_csv(
        frame(fbs, [*PUMP_PREFIX, *[f"cgm_d{n}__fasting_cgm_0600" for n in range(1, 15)]]),
        out / f"{prefix}_FBS_24H_D1-14_Results.csv",
    )
    write_csv(frame(scalars, scalar_columns()), out / f"{prefix}_NewMetric_Results.csv")
    status_frame = frame(statuses, list(statuses[0]))
    summary_frame = frame(overview, summary_columns())
    write_csv(status_frame, out / "2204_PatientStatus.csv")
    write_csv(request.loc[:, list(PUMP_PREFIX)], out / "2204_RequestList.csv")
    write_csv(summary_frame, out / f"{prefix}_Patient_Summary.csv")
    full_columns = [*PUMP_PREFIX, *ASSETS["full7"].fields]
    sparse_columns = [*PUMP_PREFIX, *ASSETS["sparse5"].fields]
    write_workbook(
        out / f"{prefix}_NewMetric_Summary.xlsx",
        [
            (
                "说明",
                pd.DataFrame(
                    [
                        ("批次", root.name),
                        ("患者数", len(request)),
                        ("完成处理", sum(r["computation_status"] == "COMPUTED" for r in statuses)),
                        ("资格", "允许CGM从出院后开始；每个窗口独立检查覆盖率。"),
                        ("日界线", "出院后Dn从出院时刻加24×(n−1)小时至加24×n小时。"),
                        ("时长", "末日仍使用完整24小时覆盖率分母。"),
                        ("事件", "低血糖事件明细CSV只列正式合格窗口；零事件与缺测见窗口质量CSV。"),
                        ("精度", "小数四位；缺失留空，充分观测但无事件为零。"),
                        ("MAGE", "正式MAGE待参考验收；候选值单列。"),
                    ],
                    columns=["项目", "内容"],
                ),
            ),
            ("患者总览", summary_frame),
            ("未计算病例", status_frame.loc[status_frame.computation_status.ne("COMPUTED")]),
            ("Full7", frame(full, full_columns)),
            ("Sparse5", frame(sparse, sparse_columns)),
        ],
    )
    write_csv(status_frame, root / "patient_status.csv")
    (out / "README.md").write_text(
        f"""# CML v2.0.0 · 261112 布局订正3 / Delivery layout 3

全部表格来自同一次计算，患者数 {len(request)}，完成处理 {sum(r["computation_status"] == "COMPUTED" for r in statuses)}。
All tables come from one calculation, with {len(request)} requested patients.

## 逐日 / Daily windows

Mode0 Daily沿用首个有效CGM时刻作为起点。AfterDischarge Daily以出院时刻为起点，Dn为
[T+24×(n−1)小时,T+24×n小时)。至少D1—D7保留全部患者，后续延续至记录结束。
末日仍以完整24小时为覆盖分母。覆盖率不足70%时指标留空；无事件与缺测通过Window Quality区分。

CGM days start at the first valid reading. Post-discharge days start at discharge and span
exactly 24 hours. The final recording day retains a full 24-hour coverage denominator.
Days 1–7 retain all patients. Later days extend to each record's end. Metrics require 70% coverage.

出院后daily的主要查看文件为AfterDischarge_Daily_D1-14.xlsx，含出院前24h及Day 1—Day 14，共15页，每张表保留全部患者。
原CSV长表作为附加数据保留。Excel补充展示的无记录日保留日期、空白指标与原因，不延长观测或重算指标。

The primary follow-up display has 15 sheets: pre-discharge 24h, followed by Day 1–Day 14.
Every sheet retains all patients. Pre-discharge spans [T−24h,T); its day number is blank.
The long CSV remains post-discharge only. The added sheet reuses the saved pre24h calculation.
The existing long CSV remains available. Padded days have anchors, missing metrics and a reason;
padding does not extend observation or change computed values.

昼夜按00:00—06:00和06:00—24:00与研究窗的交集计算。单日不提供住院FBS-CV和窗内MODD；
与前一个出院后日的MODD单列，要求两日合格，D1为空。

Night and day use clock-time intersections, 00:00–06:00 and 06:00–24:00.
Follow-up daily tables omit inpatient fasting CV and within-window MODD. Previous-day MODD
compares exact 24-hour pairs and requires both days to qualify; day 1 has no previous-day value.

## 时间窗最低值 / Window-wide minimum

global_min为整个时间窗有效CGM值的最低值，单位mmol/L；它独立于是否发生低血糖事件。
每个Mode表、两个daily工作簿的每个sheet均保留一列global_min，原已有列不重复添加。
夜间/白天的global_min分别仅限对应时段。覆盖率不足或无有效计算时仍留空，不将缺失当作零。

Every Mode table and every sheet in both daily workbooks contains exactly one global_min
for the whole window (mmol/L), including windows without hypoglycemia. Period-prefixed minima
refer only to their period. Coverage eligibility is unchanged; unavailable minima remain blank.

## ATTD与患者状态 / ATTD and patient outcomes

NewMetric、Full7、Sparse5与Mode表来自同一批记录。允许CGM从出院后开始；每个窗口独立判断。
Full7保留泵开始和出院前锚点，Sparse5保留原始4/8/12取点完整性规则，不改为逐日采样。
COMPUTED表示处理完成，不表示所有窗口均可用。正式MAGE仍待参考验收，候选值单列。

NewMetric, Full7, Sparse5 and Mode tables share the same patient calculation. A file may start
after discharge. Eligibility is checked separately for every window. ATTD retains its original
pump, pre-discharge and sparse-sampling anchors. COMPUTED does not imply that all windows qualify.
Formal MAGE remains pending reference validation; its candidate is explicitly identified.

## 低血糖事件 / Hypoglycemia events

Hypoglycemia Events每行是一位患者在一个窗口、一个时段内的一次指定类型事件。
Mode和两类daily的每个低血糖次数列后紧邻_times列，每次以“起止时间 = 当次最低值”显示，最低值四位小数，多次用分号分隔。
普通低血糖、Level2、延长低血糖等可以嵌套，不得跨类型或重叠窗口直接累加。
只列相应时段覆盖合格的正式事件；未合格窗口的观测事实保存在audit中。
duration_min为事件经过时长，condition_minutes为低于阈值的支持分钟。
left_censored/right_censored说明边界或缺测截断，不代表已经观测到完整发生和恢复。
hypo_cond_thresholds保留普通事件在舍入前满足的严格最低值阈值，使用竖线分隔。

Each event row identifies a patient, window, period and event type.
Mode and both daily layouts place a readable _times column immediately after each hypoglycemia count.
Each entry is start - end = nadir_mmol_L; multiple entries are separated by semicolons.
Nadirs use four-place half-up rounding. The dedicated event table is retained unchanged.
Types can be nested and windows overlap; their counts must not be summed indiscriminately. Only qualified outcomes are
exported here. Unqualified observed facts remain in audit. Elapsed duration and below-threshold
minutes are distinct. Censor flags indicate incomplete observation. Conditional threshold
membership is determined before rounding and retained in hypo_cond_thresholds.

前六列固定信息保留；无analysis_id。时间显示日期和时分秒，小数采用十进制四舍五入至四位，
整数计数保持整数，零保留，缺失留空。Excel全表Times New Roman。CSV采用UTF-8 BOM。

The six request columns are retained, without analysis_id. Times show local date and clock time.
Decimals use four-place half-up rounding, counts remain integers, zero is retained and missing
values are blank. Excel uses Times New Roman. CSV uses UTF-8 with BOM.

## 本批统计 / Batch counts

- 出院后逐日行数 / Follow-up daily rows: {counts["after_discharge_rows"]}
- 合格逐日行数 / Qualified follow-up rows: {counts["after_discharge_qualified_rows"]}
- 最后出院后日 / Maximum follow-up day: {counts["maximum_post_discharge_day"]}
- 低血糖事件明细行数 / Hypoglycemia event rows: {counts["hypoglycemia_event_rows"]}
- 出院后Excel展示行数 / Follow-up workbook rows: {counts["after_discharge_workbook_rows"]}
- 每张Mode表的次数/时段配对 / Adjacent count/time pairs per Mode: {counts["event_time_column_pairs_per_mode"]}
""",
        encoding="utf-8",
    )
    return statuses, dict(counts)

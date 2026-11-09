"""从患者资料生成包含泵时间的请求表；不修改任何原始文件。"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from cgm_library.io.common import (
    RequestMatchError,
    anchor_precision,
    parse_local_datetime,
    read_csv_strings,
)

__all__ = [
    "PATIENT_PREFIX",
    "PUMP_PREFIX",
    "PUMP_SOURCE_COLUMNS",
    "REQUEST_PREFIX",
    "RequestMatchError",
    "augment_request",
    "derive_pump_fields",
    "parse_local_datetime",
    "read_csv_strings",
    "select_patient_source",
    "write_csv_new",
]

REQUEST_PREFIX = ("住院号", "出院日期", "入院日期", "设备文件名")
PUMP_PREFIX = REQUEST_PREFIX + ("胰岛素泵开始时间", "胰岛素泵停止时间")
PATIENT_PREFIX = ("住院号", "出院日期", "入院日期")
PUMP_SOURCE_COLUMNS = (
    "胰岛素泵开始时间",
    "胰岛素泵停止时间",
    "德谷开始时间",
    "甘精开立时间",
)


def _same_stay_day(request: dict[str, str], patient: dict[str, str]) -> bool:
    return all(
        parse_local_datetime(request[key]).date() == parse_local_datetime(patient[key]).date()
        for key in ("入院日期", "出院日期")
    )


def _same_stay_time(request: dict[str, str], patient: dict[str, str]) -> bool:
    return all(
        parse_local_datetime(request[key]) == parse_local_datetime(patient[key])
        for key in ("入院日期", "出院日期")
    )


def select_patient_source(
    request: dict[str, str], candidates: list[dict[str, str]]
) -> tuple[dict[str, str], str]:
    """先按住院号，再核对出入院；多个候选时只接受唯一的完整时刻匹配。"""
    hospital_id = request["住院号"].strip()
    if not hospital_id:
        raise RequestMatchError("请求表住院号为空")
    if not candidates:
        raise RequestMatchError(f"患者表找不到住院号 {hospital_id}")
    if len(candidates) == 1:
        if not _same_stay_day(request, candidates[0]):
            raise RequestMatchError(f"住院号 {hospital_id} 的入出院自然日不一致")
        return candidates[0], "UNIQUE_ID_AND_STAY_DATES"
    exact = [row for row in candidates if _same_stay_time(request, row)]
    if len(exact) != 1:
        raise RequestMatchError(
            f"住院号 {hospital_id} 有 {len(candidates)} 条患者记录，"
            f"完整入出院时刻匹配 {len(exact)} 条；禁止推断选行"
        )
    return exact[0], "UNIQUE_EXACT_STAY_TIME"


def _earliest_fallback(patient: dict[str, str]) -> tuple[str, str]:
    choices = []
    for key in ("德谷开始时间", "甘精开立时间"):
        raw = patient[key].strip()
        if raw:
            # 比较时只使用来源给定精度；若以后出现仅日期的停止候选，先报错而非猜中午。
            if len(raw) <= 10:
                raise RequestMatchError(f"{key} 仅有日期，泵停止时刻待裁定")
            choices.append((parse_local_datetime(raw), key, raw))
    if not choices:
        return "", "MISSING_END"
    _, key, raw = min(choices)
    return raw, key


def derive_pump_fields(patient: dict[str, str]) -> tuple[str, str, str, str]:
    """保留原始精度；补中午仅在计算解析时发生，停止时间只记载和 QC。"""
    start = patient["胰岛素泵开始时间"].strip()
    if not start:
        raise RequestMatchError("患者表泵开始时间为空")
    parse_local_datetime(start, date_only_hour=12)
    end = patient["胰岛素泵停止时间"].strip()
    source = "胰岛素泵停止时间"
    if not end:
        end, source = _earliest_fallback(patient)
    if end:
        parse_local_datetime(end)
    # 已发布的请求准备表使用这两个历史标签，计算表使用同一解析器的规范标签。
    precision = {"DATE_ONLY_NOON": "DATE_ONLY_NOON_ON_CALCULATION", "EXACT": "EXACT_TIME"}[
        anchor_precision(start, pump_start=True)
    ]
    return start, end, source, precision


def augment_request(
    request_headers: list[str],
    request_rows: list[dict[str, str]],
    patient_headers: list[str],
    patient_rows: list[dict[str, str]],
    source_row_overrides: dict[str, int] | None = None,
) -> tuple[list[str], list[dict[str, str]], list[dict[str, str | int | bool]]]:
    """全部患者先通过匹配检查；人工指定按含表头的原 CSV 行号核验。"""
    if tuple(request_headers[:4]) != REQUEST_PREFIX:
        raise RequestMatchError("旧请求表前四列与已审定表头不一致")
    if (
        tuple(patient_headers[:3]) != PATIENT_PREFIX
        or tuple(patient_headers[6:10]) != PUMP_SOURCE_COLUMNS
    ):
        raise RequestMatchError("患者表前3列或第7至10列与已核实来源契约不一致")
    if any(key in request_headers for key in PUMP_PREFIX[4:]):
        raise RequestMatchError("请求表已有泵时间列；禁止重复插入")
    if not request_rows:
        raise RequestMatchError("请求表没有患者数据行")
    overrides = source_row_overrides or {}
    request_ids = {row["住院号"].strip() for row in request_rows}
    if set(overrides) - request_ids:
        raise RequestMatchError("人工指定包含不在本次请求表中的住院号")
    by_id = defaultdict(list)
    for record_number, patient in enumerate(patient_rows, start=2):
        by_id[patient["住院号"].strip()].append((record_number, patient))
    output_headers = list(PUMP_PREFIX) + request_headers[4:]
    output_rows: list[dict[str, str]] = []
    qc_rows: list[dict[str, str | int | bool]] = []
    for number, request in enumerate(request_rows, start=2):
        hospital_id = request["住院号"].strip()
        candidates = by_id[hospital_id]
        if hospital_id in overrides:
            source_csv_row = overrides[hospital_id]
            if not isinstance(source_csv_row, int) or isinstance(source_csv_row, bool):
                raise RequestMatchError("人工指定的患者表行号必须为整数")
            if not 2 <= source_csv_row <= len(patient_rows) + 1:
                raise RequestMatchError("人工指定的患者表行号超出原 CSV 范围")
            patient = patient_rows[source_csv_row - 2]
            if patient["住院号"].strip() != hospital_id:
                raise RequestMatchError("人工指定原表行的住院号与请求表不符")
            if not _same_stay_day(request, patient):
                raise RequestMatchError("人工指定原表行的出入院自然日与请求表不符")
            match_mode = "MANUAL_SOURCE_ROW"
        else:
            patient, match_mode = select_patient_source(
                request, [record for _, record in candidates]
            )
            # 精确匹配已保证唯一；记录号始终按原表（含表头）计数。
            source_csv_row = next(number for number, record in candidates if record == patient)
        start, end, end_source, start_precision = derive_pump_fields(patient)
        row = {
            **{key: request[key] for key in REQUEST_PREFIX},
            "胰岛素泵开始时间": start,
            "胰岛素泵停止时间": end,
            **{key: request[key] for key in request_headers[4:]},
        }
        output_rows.append(row)
        end_before_or_at_start = bool(
            end and parse_local_datetime(end) <= parse_local_datetime(start, date_only_hour=12)
        )
        qc_rows.append(
            {
                "request_csv_row": number,
                "match_mode": match_mode,
                "patient_source_candidates_n": len(candidates),
                "patient_source_csv_row": source_csv_row,
                "pump_start_precision": start_precision,
                "pump_end_source": end_source,
                "pump_end_missing": not bool(end),
                "pump_end_not_after_start": end_before_or_at_start,
            }
        )
    return output_headers, output_rows, qc_rows


def write_csv_new(path: Path, headers: list[str], rows: list[dict]) -> None:
    """只创建新文件；已存在时直接失败，绝不覆盖原始请求或既有输出。"""
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)

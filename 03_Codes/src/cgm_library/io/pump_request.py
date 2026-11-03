"""从患者资料生成包含泵时间的请求表；不修改任何原始文件。"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REQUEST_PREFIX = ("住院号", "出院日期", "入院日期", "设备文件名")
PUMP_PREFIX = REQUEST_PREFIX + ("胰岛素泵开始时间", "胰岛素泵停止时间")
PATIENT_PREFIX = ("住院号", "出院日期", "入院日期")
PUMP_SOURCE_COLUMNS = (
    "胰岛素泵开始时间",
    "胰岛素泵停止时间",
    "德谷开始时间",
    "甘精开立时间",
)


class RequestMatchError(ValueError):
    """患者来源无法按已批准的身份与时间规则唯一核对。"""


def read_csv_strings(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """全部列按字符串读取，避免住院号前导零和请求附加列被类型推断改写。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                if not headers or len(headers) != len(set(headers)):
                    raise RequestMatchError(f"CSV 表头为空或有重名列：{path}")
                rows = list(reader)
                if any(None in row for row in rows):
                    raise RequestMatchError(f"CSV 存在多于表头的字段：{path}")
                return headers, rows
        except UnicodeDecodeError:
            continue
    raise RequestMatchError(f"CSV 编码无法识别：{path}")


def parse_local_datetime(value: str, *, date_only_hour: int | None = None) -> datetime:
    """北京本地时间，无夏令时；仅日期的泵开始时间按已批准规则补 12:00。"""
    raw = str(value).strip().replace("/", "-")
    if not raw:
        raise RequestMatchError("必需的时间值为空")
    try:
        result = datetime.fromisoformat(raw)
    except ValueError as exc:
        # 患者原表存在单数字小时（例如 8:48），Python 的 ISO 解析不接受；
        # 仅补充明确的本地日期/时分/秒格式，仍拒绝含糊的月日顺序和时区。
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                result = datetime.strptime(raw, pattern)  # noqa: DTZ007 北京本地墙上时间
                break
            except ValueError:
                continue
        else:
            raise RequestMatchError(f"时间格式无法解析：{raw!r}") from exc
    if result.tzinfo is not None:
        raise RequestMatchError("输入含时区偏移；此项目要求北京本地时间字符串")
    if len(raw) <= 10 and date_only_hour is not None:
        result = result.replace(hour=date_only_hour)
    return result


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
    precision = "DATE_ONLY_NOON_ON_CALCULATION" if len(start) <= 10 else "EXACT_TIME"
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
    by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    source_row_by_identity = {id(row): index for index, row in enumerate(patient_rows, start=2)}
    for patient in patient_rows:
        by_id[patient["住院号"].strip()].append(patient)
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
            patient, match_mode = select_patient_source(request, candidates)
            # 身份相同也不意味着来源行可以猜测；用被选对象反查物理 CSV 行。
            source_csv_row = source_row_by_identity[id(patient)]
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

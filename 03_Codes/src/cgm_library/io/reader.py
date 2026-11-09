"""请求表与设备文件只读加载；不按相似文件名猜测患者来源。"""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

import pandas as pd
from xlrd.biffh import XLRDError

from cgm_library.contracts.fields import check_request_columns
from cgm_library.contracts.schema import CalculationError, RunConfig
from cgm_library.io.common import parse_local_datetime, read_csv_strings
from cgm_library.io.pump_request import PUMP_PREFIX

TIMEZONE = "Asia/Shanghai"


def parse_anchor(value: str, *, pump_start: bool = False) -> pd.Timestamp:
    """普通仅日期锚点补 00:00；仅日期泵开始补 12:00，并由上游保留精度 QC。"""
    try:
        naive = parse_local_datetime(value, date_only_hour=12 if pump_start else 0)
    except ValueError as exc:
        raise CalculationError("ERROR04", f"研究锚点时间无法解析：{value!r}") from exc
    return pd.Timestamp(naive).tz_localize(TIMEZONE)


def read_request(path: Path, *, content: bytes | None = None) -> pd.DataFrame:
    """前六列固定；第七列起原样保留并输出，不擅自丢弃比对字段。"""
    try:
        headers, rows = read_csv_strings(path, content=content)
    except ValueError as exc:
        raise CalculationError("ERROR03", str(exc), "batch") from exc
    if tuple(headers[:6]) != PUMP_PREFIX:
        raise CalculationError("ERROR03", "请求表前六列不符合泵时间新契约", "batch")
    check_request_columns(headers)
    data = pd.DataFrame(rows, columns=headers)
    if "analysis_id" not in data:
        data["analysis_id"] = [f"request-{i + 1:04d}" for i in range(len(data))]
    if data.analysis_id.eq("").any() or data.analysis_id.duplicated().any():
        raise CalculationError("ERROR02", "analysis_id 为空或重复", "batch")
    data["request_row"] = range(2, len(data) + 2)
    return data


def locate_source(row: dict[str, str], config: RunConfig) -> tuple[Path, object]:
    """按出院自然日选唯一批次，再按精确设备 basename 选唯一文件。"""
    discharge = parse_anchor(row["出院日期"])
    folders = [source for source in config.sources if source.contains(discharge)]
    if len(folders) != 1:
        raise CalculationError("ERROR02", "出院日期对应来源批次非唯一")
    source = folders[0]
    if any(part.lower().endswith("_cleaned") for part in source.path.parts):
        raise CalculationError("ERROR05", "cleaned仅备份，禁止作为计算来源")
    name = str(row["设备文件名"]).strip()
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise CalculationError("ERROR02", "设备文件名缺失或不是单一文件名")
    if Path(name).suffix.lower() in (".csv", ".xlsx", ".xls"):
        choices = [source.path / name]
    else:
        choices = [source.path / f"{name}{ext}" for ext in (".csv", ".xlsx", ".xls")]
    existing = [candidate for candidate in choices if candidate.is_file()]
    if len(existing) != 1:
        raise CalculationError(
            "ERROR01" if not existing else "ERROR02",
            "原始 CGM 文件未找到" if not existing else "同名多格式原始文件非唯一",
        )
    return existing[0], source


def read_cgm(path: Path, source_unit: str, *, content: bytes | None = None) -> pd.DataFrame:
    """仅认已核查的设备列格式；原始时间、血糖字符串与源行号全部保留。"""
    if path.suffix.lower() == ".csv":
        try:
            headers, rows = read_csv_strings(path, content=content)
        except ValueError as exc:
            raise CalculationError("ERROR03", str(exc)) from exc
        source = pd.DataFrame(rows, columns=headers)
    elif path.suffix.lower() in (".xlsx", ".xls"):
        try:
            # header=None 保留真实重名表头，避免 pandas 自动改成 T.1 后失去证据。
            book = pd.read_excel(
                BytesIO(content if content is not None else path.read_bytes()),
                header=None,
                dtype=str,
                keep_default_na=False,
            )
        except (ValueError, BadZipFile, XLRDError) as exc:
            raise CalculationError("ERROR03", "无法解析 CGM Excel 工作簿") from exc
        if book.empty:
            raise CalculationError("ERROR03", "CGM 文件为空")
        headers = list(book.iloc[0])
        source = book.iloc[1:].reset_index(drop=True).copy()
        source.columns = ["Unnamed: 0", "Unnamed: 1"] if headers == ["", ""] else headers
    else:
        raise CalculationError("ERROR03", "CGM 文件扩展名不受支持")
    if source.empty:
        raise CalculationError("ERROR03", "CGM 文件为空")
    aliases = defaultdict(list)
    for col in source.columns:
        aliases[str(col).strip().lower()].append(col)
    collisions = [names for names in aliases.values() if len(names) > 1]
    if collisions:
        raise CalculationError("ERROR03", f"规范化后设备列名冲突：{collisions}")
    columns = {key: names[0] for key, names in aliases.items()}
    if {"t", "v"} <= columns.keys():
        time_col, value_col = columns["t"], columns["v"]
    elif {"日期时间(时分秒)", "血糖值"} <= columns.keys():
        time_col, value_col = columns["日期时间(时分秒)"], columns["血糖值"]
    elif {"timestamp", "glucose"} <= columns.keys():
        time_col, value_col = columns["timestamp"], columns["glucose"]
    elif list(source.columns) == ["Unnamed: 0", "Unnamed: 1"]:
        # 早期 241130 设备导出确有空白表头且严格只有两列；首个实际读数在 Excel 第 2 行。
        # 只接受这一种已观察到的无标题模板，未知双列文件仍明确停止。
        time_col, value_col = source.columns
    else:
        raise CalculationError("ERROR03", "未知 CGM 列格式，不能任取前两列")
    data = pd.DataFrame(
        {
            "raw_time": source[time_col].astype(str),
            "glucose_raw": source[value_col].astype(str),
            "source_row": range(2, len(source) + 2),
            "source_unit": source_unit,
        }
    )
    state_columns = [
        column
        for column in source.columns
        if str(column).strip().lower() in ("status", "device_status", "error", "错误码", "状态")
    ]
    if len(state_columns) > 1:
        raise CalculationError("ERROR03", f"设备状态列不唯一：{state_columns}")
    if state_columns:
        data["device_state"] = source[state_columns[0]].astype(str)
    return data

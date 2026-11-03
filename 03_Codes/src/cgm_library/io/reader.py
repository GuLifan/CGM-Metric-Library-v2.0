"""请求表与设备文件只读加载；不按相似文件名猜测患者来源。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cgm_library.contracts.schema import CalculationError, RunConfig
from cgm_library.io.pump_request import PUMP_PREFIX, parse_local_datetime, read_csv_strings

TIMEZONE = "Asia/Shanghai"


def parse_anchor(value: str, *, pump_start: bool = False) -> pd.Timestamp:
    """普通仅日期锚点补 00:00；仅日期泵开始补 12:00，并由上游保留精度 QC。"""
    try:
        naive = parse_local_datetime(value, date_only_hour=12 if pump_start else 0)
    except ValueError as exc:
        raise CalculationError("ERROR04", f"研究锚点时间无法解析：{value!r}") from exc
    return pd.Timestamp(naive).tz_localize(TIMEZONE)


def read_request(path: Path) -> pd.DataFrame:
    """前六列固定；第七列起原样保留并输出，不擅自丢弃比对字段。"""
    try:
        headers, rows = read_csv_strings(path)
    except ValueError as exc:
        raise CalculationError("ERROR03", str(exc), "batch") from exc
    if tuple(headers[:6]) != PUMP_PREFIX:
        raise CalculationError("ERROR03", "请求表前六列不符合泵时间新契约", "batch")
    forbidden = {"request_row", "run_id", "patient_status", "window_name"}
    if set(headers) & forbidden:
        raise CalculationError("ERROR03", "请求表附加列与结果保留列冲突", "batch")
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


def read_cgm(path: Path, source_unit: str) -> pd.DataFrame:
    """仅认已核查的设备列格式；原始时间、血糖字符串与源行号全部保留。"""
    if path.suffix.lower() == ".csv":
        try:
            headers, rows = read_csv_strings(path)
        except ValueError as exc:
            raise CalculationError("ERROR03", str(exc)) from exc
        source = pd.DataFrame(rows, columns=headers)
    elif path.suffix.lower() in (".xlsx", ".xls"):
        source = pd.read_excel(path, dtype=str, keep_default_na=False)
    else:
        raise CalculationError("ERROR03", "CGM 文件扩展名不受支持")
    if source.empty:
        raise CalculationError("ERROR03", "CGM 文件为空")
    columns = {str(column).strip().lower(): column for column in source.columns}
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
    if state_columns:
        data["device_state"] = source[state_columns[0]].astype(str)
    return data

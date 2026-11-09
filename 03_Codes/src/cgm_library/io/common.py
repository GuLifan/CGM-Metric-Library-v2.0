"""请求与设备读取共用的 CSV 及北京时间解析。"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path


class RequestMatchError(ValueError):
    """患者来源无法按已批准的身份与时间规则唯一核对。"""


def read_csv_strings(
    path: Path, *, content: bytes | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """全部列按字符串读取，避免住院号前导零和请求附加列被类型推断改写。"""
    content = path.read_bytes() if content is None else content
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with io.StringIO(content.decode(encoding), newline="") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                if not headers or len(headers) != len(set(headers)):
                    raise RequestMatchError(f"CSV 表头为空或有重名列：{path}")
                rows = list(reader)
                if any(None in row or None in row.values() for row in rows):
                    raise RequestMatchError(f"CSV 行字段数与表头不一致：{path}")
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


def anchor_precision(text: str, *, pump_start=False) -> str:
    """记录源时间精度和实际使用的补全时刻。"""
    if not text:
        return "MISSING"
    if len(text.strip()) <= 10:
        return "DATE_ONLY_NOON" if pump_start else "DATE_ONLY_MIDNIGHT"
    return "EXACT"

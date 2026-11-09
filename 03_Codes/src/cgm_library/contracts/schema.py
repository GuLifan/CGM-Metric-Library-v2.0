"""运行配置和来源日期区间；所有配置错误在批次读取前定位。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class CalculationError(Exception):
    """稳定错误码以及错误所属的文件、患者或批次。"""

    def __init__(self, code: str, message: str, scope: str = "file") -> None:
        super().__init__(message)
        self.code = code
        self.scope = scope


def _config_error(key, reason):
    return CalculationError("ERROR03", f"配置字段 {key}：{reason}", "batch")


def _date(value, key):
    if value is None:
        return None
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise _config_error(key, "需要有效的 YYYY-MM-DD 日期")


def _number(value, key, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _config_error(key, "需要数值")
    try:
        parsed = float(value)
    except (ValueError, OverflowError) as exc:
        raise _config_error(key, "需要有限数值") from exc
    if not math.isfinite(parsed) or (integer and not parsed.is_integer()):
        raise _config_error(key, "数值非有限或不是所需的整数")
    return int(parsed) if integer else parsed


@dataclass(frozen=True)
class SourceFolder:
    path: Path
    interval_min: int
    unit: str
    from_date: date | str | None = None
    to_date: date | str | None = None

    def __post_init__(self):
        for key in ("from_date", "to_date"):
            object.__setattr__(self, key, _date(getattr(self, key), key))
        if self.from_date and self.to_date and self.from_date >= self.to_date:
            raise _config_error("from_date/to_date", "起点须早于终点")

    def contains(self, discharge: pd.Timestamp) -> bool:
        day = discharge.date()
        return (self.from_date is None or day >= self.from_date) and (
            self.to_date is None or day < self.to_date
        )


@dataclass(frozen=True)
class RunConfig:
    sources: tuple[SourceFolder, ...]
    coverage_pct: float = 70.0
    night_start_hour: int = 0
    night_end_hour: int = 6

    def __post_init__(self):
        if (self.night_start_hour, self.night_end_hour) != (0, 6):
            raise _config_error("night_start_hour/night_end_hour", "合同夜间字段固定为 00:00—06:00")
        if not 70 <= self.coverage_pct <= 100:
            raise _config_error("coverage_pct", "应在 70—100 之间")

    def snapshot(self):
        return {
            "sources": [
                {
                    "path": str(s.path.resolve()),
                    "interval_min": s.interval_min,
                    "unit": s.unit,
                    "from_date": s.from_date.isoformat() if s.from_date else None,
                    "to_date": s.to_date.isoformat() if s.to_date else None,
                }
                for s in self.sources
            ],
            "coverage_pct": self.coverage_pct,
            "night_start_hour": self.night_start_hour,
            "night_end_hour": self.night_end_hour,
        }


def load_config(path: Path, *, content: bytes | None = None) -> tuple[RunConfig, dict[str, Any]]:
    """从同一份配置字节解析，来源路径以原配置目录为基准。"""
    try:
        settings = yaml.safe_load(
            (path.read_bytes() if content is None else content).decode("utf-8-sig")
        )
    except (yaml.YAMLError, UnicodeError) as exc:
        raise _config_error("YAML", str(exc)) from exc
    if not isinstance(settings, dict):
        raise _config_error("YAML", "需要映射")
    extra = set(settings) - {"sources", "coverage_pct", "night_start_hour", "night_end_hour"}
    if extra:
        raise _config_error("YAML", f"未知字段 {list(extra)}")
    raw_sources = settings.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise _config_error("sources", "需要非空列表")
    sources = []
    for i, source in enumerate(raw_sources):
        key = f"sources[{i}]"
        if not isinstance(source, dict) or set(source) - {
            "path",
            "interval_min",
            "unit",
            "from_date",
            "to_date",
        }:
            raise _config_error(key, "来源字段不合法")
        folder = source.get("path")
        if not isinstance(folder, str) or not folder.strip():
            raise _config_error(f"{key}.path", "需要非空目录名")
        interval = _number(source.get("interval_min"), f"{key}.interval_min", integer=True)
        unit = source.get("unit")
        if interval not in (1, 5) or unit not in ("mmol/L", "mg/dL"):
            raise CalculationError(
                "ERROR05", f"{key}.interval_min/unit 来源频率或单位不支持", "batch"
            )
        folder = (path.parent / Path(folder).expanduser()).resolve()
        s = SourceFolder(
            folder,
            interval,
            unit,
            _date(source.get("from_date"), f"{key}.from_date"),
            _date(source.get("to_date"), f"{key}.to_date"),
        )
        for other in sources:
            if (other.to_date is None or s.from_date is None or s.from_date < other.to_date) and (
                s.to_date is None or other.from_date is None or other.from_date < s.to_date
            ):
                raise _config_error(key, "来源日期区间重叠")
        sources.append(s)
    return RunConfig(
        tuple(sources),
        _number(settings.get("coverage_pct", 70), "coverage_pct"),
        _number(settings.get("night_start_hour", 0), "night_start_hour", True),
        _number(settings.get("night_end_hour", 6), "night_end_hour", True),
    ), settings

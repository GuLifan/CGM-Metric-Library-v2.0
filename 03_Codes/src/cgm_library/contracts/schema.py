"""运行配置只声明来源和项目参数，不改写医学指标定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class CalculationError(Exception):
    """带稳定代码和作用范围的可审计计算终止。"""

    def __init__(self, code: str, message: str, scope: str = "file") -> None:
        super().__init__(message)
        self.code = code
        self.scope = scope


@dataclass(frozen=True)
class SourceFolder:
    path: Path
    interval_min: int
    unit: str
    from_date: str | None = None
    to_date: str | None = None

    def contains(self, discharge: pd.Timestamp) -> bool:
        date = discharge.date().isoformat()
        return (not self.from_date or date >= self.from_date) and (
            not self.to_date or date < self.to_date
        )


@dataclass(frozen=True)
class RunConfig:
    sources: tuple[SourceFolder, ...]
    coverage_pct: float = 70.0
    night_start_hour: int = 0
    night_end_hour: int = 6


def load_config(path: Path) -> tuple[RunConfig, dict[str, Any]]:
    """只接受明确字段；相对来源目录以配置文件所在目录为基准。"""
    settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise CalculationError("ERROR03", "配置文件必须为 YAML 映射", "batch")
    allowed = {"sources", "coverage_pct", "night_start_hour", "night_end_hour"}
    unknown = set(settings) - allowed
    if unknown:
        raise CalculationError("ERROR03", f"未知配置字段：{sorted(unknown)}", "batch")
    raw_sources = settings.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise CalculationError("ERROR03", "来源目录配置为空", "batch")
    sources = []
    for source in raw_sources:
        if not isinstance(source, dict) or set(source) - {
            "path",
            "interval_min",
            "unit",
            "from_date",
            "to_date",
        }:
            raise CalculationError("ERROR03", "来源配置字段不合法", "batch")
        try:
            folder = Path(source["path"]).expanduser()
            if not folder.is_absolute():
                folder = path.parent / folder
            interval = int(source["interval_min"])
            unit = str(source["unit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CalculationError("ERROR03", "来源路径、频率或单位缺失", "batch") from exc
        if interval not in (1, 5) or unit not in ("mmol/L", "mg/dL"):
            raise CalculationError("ERROR05", "来源频率或血糖单位未确认", "batch")
        sources.append(
            SourceFolder(
                folder.resolve(), interval, unit, source.get("from_date"), source.get("to_date")
            )
        )
    coverage = float(settings.get("coverage_pct", 70))
    night_start = int(settings.get("night_start_hour", 0))
    night_end = int(settings.get("night_end_hour", 6))
    if not 70 <= coverage <= 100 or not 0 <= night_start < night_end <= 24:
        raise CalculationError("ERROR03", "覆盖率或夜窗参数超出已批准范围", "batch")
    return RunConfig(tuple(sources), coverage, night_start, night_end), settings

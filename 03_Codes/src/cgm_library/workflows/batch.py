"""受控本地部分批次：逐患者继续、逐资产哈希，明确禁止冒充完整交付。"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from collections import Counter
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from cgm_library.contracts.schema import CalculationError, load_config
from cgm_library.io.reader import read_request
from cgm_library.timeline.groups import TimelineError
from cgm_library.workflows.patient import calculate_patient_partial


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _code_revision() -> str | None:
    """记录本地 Git 提交；尚无 Git 的离线副本写 null，不伪造版本。"""
    root = Path(__file__).resolve().parents[4]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _csv(path: Path, frames: list[pd.DataFrame], *, columns: list[str] | None = None) -> None:
    """即使某类事件没有发生，也留带表头的空长表供下游识别。"""
    nonempty = [frame for frame in frames if not frame.empty]
    table = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame(columns=columns)
    table.to_csv(path, index=False, encoding="utf-8-sig")


def run_partial_batch(
    request_path: Path,
    config_path: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    """运行所有可确定字段；MAGE参考验收保持明确未发布状态。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("run_id 只能包含字母、数字、下划线和短横线")
    config, _ = load_config(config_path)
    request = read_request(request_path)
    if request.empty:
        raise CalculationError("ERROR03", "请求表没有患者数据行", "batch")
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    qc_dir = output / "qc_and_coverage"
    metrics_dir = output / "metric_outputs"
    log_dir = output / "logs"
    timeline_dir = qc_dir / "timeline_groups"
    for directory in (qc_dir, metrics_dir, log_dir, timeline_dir):
        directory.mkdir()
    (output / "config.yaml").write_bytes(config_path.read_bytes())
    (output / "environment.yaml").write_text(
        "\n".join(
            (
                f"python: {platform.python_version()}",
                f"pandas: {version('pandas')}",
                f"numpy: {version('numpy')}",
                f"library: {version('cgm-metric-library')}",
                "run_mode: PARTIAL_RULE_GATED",
                "",
            )
        ),
        encoding="utf-8",
    )
    collected: dict[str, list[pd.DataFrame]] = {
        "window": [],
        "day_night": [],
        "daily_risk": [],
        "fasting": [],
        "event": [],
        "night_event": [],
        "sparse20": [],
        "candidates": [],
        "sparse5": [],
        "full7": [],
        "file_qc": [],
        "intervals": [],
        "anomalies": [],
    }
    statuses: list[dict[str, object]] = []
    for request_index, (_, record) in enumerate(request.iterrows(), start=1):
        row = record.to_dict()
        try:
            result = calculate_patient_partial(row, config)
        except (CalculationError, TimelineError, ValueError, OSError) as exc:
            statuses.append(
                {
                    **row,
                    "patient_status": "ERROR",
                    "error_code": getattr(exc, "code", "ERROR99"),
                    "error_message": str(exc),
                }
            )
            continue
        statuses.append(
            {
                **row,
                "patient_status": result.status,
                "error_code": "",
                "error_message": "",
                "pump_qc_reason": result.qc.get("pump_qc_reason", ""),
            }
        )
        collected["window"].append(result.window_rows)
        collected["day_night"].append(result.day_night_rows)
        collected["daily_risk"].append(result.daily_risk_rows)
        collected["fasting"].append(result.fasting_day_rows)
        collected["event"].append(result.event_rows)
        collected["night_event"].append(result.night_event_rows)
        collected["sparse20"].append(result.sparse_targets)
        collected["candidates"].append(result.sparse_candidates)
        collected["sparse5"].append(pd.DataFrame([{**row, **result.sparse5}]))
        collected["full7"].append(pd.DataFrame([{**row, **result.full7}]))
        collected["file_qc"].append(pd.DataFrame([{**row, **result.qc}]))
        collected["intervals"].append(
            pd.DataFrame([{**row, **entry} for entry in result.raw_intervals])
        )
        anomalies = result.raw_evidence.loc[result.raw_evidence.qc_reason.ne("OK")]
        if not anomalies.empty:
            collected["anomalies"].append(anomalies.assign(analysis_id=row["analysis_id"]))
        # 来源组行号是重跑证据；分患者保存避免把所有时间轴堆成超宽表。
        result.groups.to_csv(
            timeline_dir / f"request_{request_index:04d}.csv", index=False, encoding="utf-8-sig"
        )
    status = pd.DataFrame(statuses)
    status.to_csv(log_dir / "patient_status.csv", index=False, encoding="utf-8-sig")
    assets = {
        qc_dir / "patient_file_qc.csv": "file_qc",
        qc_dir / "daily_risk.csv": "daily_risk",
        qc_dir / "fasting_day.csv": "fasting",
        qc_dir / "raw_intervals.csv": "intervals",
        qc_dir / "raw_anomalies.csv": "anomalies",
        metrics_dir / "patient_window_metrics.csv": "window",
        metrics_dir / "patient_day_night_long.csv": "day_night",
        metrics_dir / "event_level_long_table.csv": "event",
        metrics_dir / "night_event_level_long_table.csv": "night_event",
        metrics_dir / "attd_sparse20_targets.csv": "sparse20",
        metrics_dir / "attd_sparse20_candidates.csv": "candidates",
        metrics_dir / "attd_sparse5.csv": "sparse5",
        metrics_dir / "attd_full7.csv": "full7",
    }
    for path, key in assets.items():
        expected_columns = list(request.columns)
        if key in ("event", "night_event"):
            expected_columns += [
                "event_id",
                "event_type",
                "event_start",
                "event_end",
                "duration_min",
                "nadir",
                "peak",
                "left_censored",
                "right_censored",
                "outcome_qualified",
                "window_name",
                "window_start",
                "window_end",
            ]
        _csv(path, collected[key], columns=expected_columns)
    counts = Counter(status.patient_status)
    manifest = {
        "run_id": run_id,
        "created_at_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "status": "PARTIAL_WITH_PATIENT_ERRORS" if counts.get("ERROR", 0) else "PARTIAL_RULE_GATED",
        "formal_release": False,
        "patient_count": len(request),
        "patient_status_counts": dict(counts),
        "code_commit": _code_revision(),
        "pending_rule_gates": ["MAGE_REFERENCE_VALIDATION"],
        "input_sha256": {"request": _sha256(request_path), "config": _sha256(config_path)},
        "outputs_sha256": {
            str(path.relative_to(output)): _sha256(path)
            for path in output.rglob("*")
            if path.is_file()
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output

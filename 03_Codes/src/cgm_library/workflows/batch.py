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

from cgm_library.contracts.fields import ASSETS, SCHEMA_VERSION, Asset
from cgm_library.contracts.schema import CalculationError, load_config
from cgm_library.io.reader import parse_anchor, read_request
from cgm_library.io.tables import write_csv, write_workbook
from cgm_library.qc.raw import RawEvidenceError, raw_interval_distribution
from cgm_library.timeline.groups import TimelineError
from cgm_library.workflows.patient import calculate_patient_partial


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _code_provenance():
    """提交号和实际参与计算的源码分别取证，支持无 Git 的 wheel 安装。"""
    package = Path(__file__).resolve().parents[1]
    sources = {
        path.relative_to(package).as_posix(): _sha256(path)
        for path in sorted(package.rglob("*.py"))
    }
    evidence = {"code_commit": None, "git_dirty": None, "code_sha256": sources}
    root = package.parents[2]
    if not (root / ".git").exists():
        return evidence
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError:
        return evidence
    if commit.returncode == 0:
        evidence["code_commit"] = commit.stdout.strip()
    if status.returncode == 0:
        evidence["git_dirty"] = bool(status.stdout.strip())
    return evidence


def _json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_bytes(path, content):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _csv(path: Path, frames: list[pd.DataFrame], asset: Asset, request_columns) -> None:
    """非空输入须与字段注册表一致，空表也按相同顺序发布。"""
    columns = asset.columns(request_columns)
    nonempty = []
    for frame in frames:
        if frame.empty:
            continue
        missing = set(columns) - set(frame.columns) - asset.optional
        extra = set(frame.columns) - set(columns)
        if missing or extra or not frame.columns.is_unique:
            raise ValueError(
                f"{asset.path} 输出字段不符，缺少 {sorted(missing)}，多出 {sorted(extra)}"
            )
        nonempty.append(frame)
    table = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()
    table = table.reindex(columns=columns)
    for name in asset.fields:
        if name.endswith(("_n", "_any")):
            table[name] = table[name].astype("Int64")
    temporary = path.with_suffix(".csv.tmp")
    write_csv(table, temporary)
    temporary.replace(path)


def run_partial_batch(
    request_path: Path,
    config_path: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    """运行所有可确定字段；MAGE参考验收保持明确未发布状态。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise CalculationError("ERROR03", "run_id 只能包含字母、数字、下划线和短横线", "batch")
    config_bytes = config_path.read_bytes()
    request_bytes = request_path.read_bytes()
    config, _ = load_config(config_path, content=config_bytes)
    request = read_request(request_path, content=request_bytes)
    if request.empty:
        raise CalculationError("ERROR03", "请求表没有患者数据行", "batch")
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    state = {
        "run_id": run_id,
        "status": "RUNNING",
        "formal_release": False,
        "patient_count": len(request),
    }
    statuses = []
    _write_bytes(output / "run_state.json", _json_bytes(state))
    try:
        return _execute(output, config, config_bytes, request, request_bytes, statuses, state)
    except (Exception, KeyboardInterrupt) as exc:
        state.update(
            status="ABORTED", completed_patients=len(statuses), error_type=type(exc).__name__
        )
        _write_bytes(output / "run_state.json", _json_bytes(state))
        if (output / "logs").is_dir():
            _csv(
                output / ASSETS["status"].path,
                [pd.DataFrame(statuses)],
                ASSETS["status"],
                request.columns,
            )
            import traceback

            (output / "logs/batch_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise


def _collect_raw_qc(collected, row, evidence, intervals):
    collected["intervals"].append(pd.DataFrame([{**row, **entry} for entry in intervals]))
    duplicates = evidence.timestamp.notna() & evidence.timestamp.duplicated(keep=False)
    anomalies = evidence.loc[duplicates | evidence.qc_reason.ne("OK")]
    if not anomalies.empty:
        collected["anomalies"].append(anomalies.assign(analysis_id=row["analysis_id"]))


def _execute(output, config, config_bytes, request, request_bytes, statuses, state):
    qc_dir = output / "qc_and_coverage"
    metrics_dir = output / "metric_outputs"
    log_dir = output / "logs"
    timeline_dir = qc_dir / "timeline_groups"
    for directory in (qc_dir, metrics_dir, log_dir, timeline_dir):
        directory.mkdir()
    (output / "config.yaml").write_bytes(config_bytes)
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
    collected = {key: [] for key in ASSETS}
    for request_index, (_, record) in enumerate(request.iterrows(), start=1):
        row = record.to_dict()
        try:
            result = calculate_patient_partial(row, config)
        except (CalculationError, TimelineError) as exc:
            if isinstance(exc, CalculationError) and exc.scope == "batch":
                raise
            if isinstance(exc, RawEvidenceError):
                _collect_raw_qc(
                    collected, row, exc.evidence, raw_interval_distribution(exc.evidence)
                )
            statuses.append(
                {
                    **row,
                    "patient_status": "ERROR",
                    "error_code": getattr(exc, "code", "ERROR99"),
                    "error_message": str(exc),
                    "pump_qc_reason": "",
                    "computation_status": "DATA_ERROR",
                    "warning_codes": "",
                }
            )
            continue
        warnings = []
        if result.qc["cgm_start_first_valid_raw_time"] >= parse_anchor(row["出院日期"]):
            warnings.append("CGM_START_AT_OR_AFTER_DISCHARGE")
        if result.qc["pump_qc_reason"]:
            warnings.append(result.qc["pump_qc_reason"])
        if not result.window_rows.sufficient_flag.all():
            warnings.append("COVERAGE_BELOW_THRESHOLD")
        statuses.append(
            {
                **row,
                "computation_status": "COMPUTED",
                "warning_codes": "|".join(warnings),
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
        _collect_raw_qc(collected, row, result.raw_evidence, result.raw_intervals)
        # 来源组行号是重跑证据；分患者保存避免把所有时间轴堆成超宽表。
        timeline_path = timeline_dir / f"request_{request_index:04d}.csv"
        temporary = timeline_path.with_suffix(".csv.tmp")
        write_csv(result.groups, temporary)
        temporary.replace(timeline_path)
    status = pd.DataFrame(statuses)
    collected["status"] = [status]
    for key, asset in ASSETS.items():
        _csv(output / asset.path, collected[key], asset, request.columns)
    sheets = [
        (
            "说明",
            pd.DataFrame(
                [
                    ("批次", state["run_id"]),
                    ("请求数", len(status)),
                    ("精度", "数值结果四舍五入至四位小数；空白表示缺失。"),
                    ("MAGE", "正式字段待参考验收，候选值见窗口表。"),
                ],
                columns=["项目", "内容"],
            ),
        ),
        ("患者总览", status),
        ("未计算病例", status.loc[status.computation_status.ne("COMPUTED")]),
    ]
    for key, title in [("window", "窗口指标"), ("full7", "Full7"), ("sparse5", "Sparse5")]:
        columns = ASSETS[key].columns(request.columns)
        frame = pd.concat(collected[key], ignore_index=True) if collected[key] else pd.DataFrame()
        sheets.append((title, frame.reindex(columns=columns)))
    write_workbook(output / f"{state['run_id']}_patient_summary.xlsx", sheets)
    counts = Counter(status.patient_status)
    errors = counts.get("ERROR", 0)
    outcome = (
        "ALL_PATIENTS_FAILED"
        if errors == len(request)
        else ("PARTIAL_WITH_PATIENT_ERRORS" if errors else "PARTIAL_RULE_GATED")
    )
    terminal_state = _json_bytes(state | {"status": outcome, "completed_patients": len(status)})
    manifest = {
        "run_id": state["run_id"],
        "schema_version": SCHEMA_VERSION,
        "table_decimal_places": 4,
        "created_at_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "status": outcome,
        "formal_release": False,
        "patient_count": len(request),
        "patient_status_counts": dict(counts),
        **_code_provenance(),
        "effective_config": config.snapshot(),
        "pending_rule_gates": ["MAGE_REFERENCE_VALIDATION"],
        "input_sha256": {
            "request": hashlib.sha256(request_bytes).hexdigest(),
            "config": hashlib.sha256(config_bytes).hexdigest(),
        },
        "outputs_sha256": {
            path.relative_to(output).as_posix(): _sha256(path)
            for path in output.rglob("*")
            if path.is_file()
        },
    }
    manifest["outputs_sha256"]["run_state.json"] = hashlib.sha256(terminal_state).hexdigest()
    _write_bytes(output / "manifest.json", _json_bytes(manifest))
    _write_bytes(
        output / "manifest.sha256",
        (_sha256(output / "manifest.json") + "  manifest.json\n").encode("ascii"),
    )
    _write_bytes(output / "run_state.json", terminal_state)
    return output

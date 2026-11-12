"""One batch entry point for the approved 15-file DRQ delivery."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from cgm_library.contracts.schema import CalculationError, load_config
from cgm_library.io.pump_request import PUMP_PREFIX
from cgm_library.io.reader import read_request
from cgm_library.io.tables import write_csv, write_workbook
from cgm_library.studies.drq import GROUP_FILES, PREFIX, result_columns
from cgm_library.timeline.groups import TimelineError
from cgm_library.workflows.batch import _code_provenance, _sha256
from cgm_library.workflows.drq_patient import calculate_drq_patient, result_json


def _save(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(result_json(data) + "\n", encoding="utf-8")
    temp.replace(path)


def _worker(task):
    index, row, config, path, extended = task
    try:
        result = calculate_drq_patient(row, config, extended=extended)
        result.update(computation_status="COMPUTED", error_code="", error_message="")
        if extended:
            # Structured event facts and nadirs remain in audit. Do not duplicate
            # them dozens of times as JSON strings in every conditional column.
            for values in result["tables"].values():
                for name in list(values):
                    if name.endswith("_json"):
                        del values[name]
    except (CalculationError, TimelineError) as exc:
        if isinstance(exc, CalculationError) and exc.scope == "batch":
            raise
        result = {
            "tables": {},
            "fbs": {},
            "audit": {},
            "computation_status": "DATA_ERROR",
            "error_code": getattr(exc, "code", "ERROR99"),
            "error_message": str(exc),
        }
    result["request"] = row
    _save(path, result)
    return index, result["computation_status"]


def _frame(records, columns, text):
    frame = pd.DataFrame(records).reindex(columns=columns)
    for column in frame:
        if column in text or column.endswith("_json"):
            continue
        # Serialized result numbers are four-place strings. Restore Excel numeric cell types.
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if column.endswith(("_n", "_any")):
            frame[column] = frame[column].astype("Int64")
    return frame


def _excel_parts(frame):
    """Split long JSON across adjacent cells to retain events beyond Excel's text limit."""
    result = {}
    for column in frame:
        series = frame[column]
        if column.endswith("_json"):
            maximum = series.dropna().map(len).max()
            count = max(1, (int(maximum) + 31999) // 32000) if pd.notna(maximum) else 1
            for index in range(count):
                name = column if index == 0 else f"{column}__part{index + 1}"
                result[name] = series.map(
                    lambda value, offset=index * 32000: (
                        value[offset : offset + 32000] if isinstance(value, str) else value
                    )
                )
        else:
            result[column] = series
    return pd.DataFrame(result)


def _export(root, request, request_columns):
    audit_dir = root / "audit"
    deliver = root / "results"
    deliver.mkdir(exist_ok=True)
    paths = [audit_dir / f"request_{i:04d}.json" for i in range(1, len(request) + 1)]
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    text = set(request_columns) | {"window_start", "window_end"}
    for window, suffix in GROUP_FILES.items():
        columns = result_columns(request_columns)
        frame = _frame([r["request"] | r["tables"].get(window, {}) for r in records], columns, text)
        write_csv(frame, deliver / f"{PREFIX}_{suffix}")
    fbs_columns = request_columns + [f"cgm_d{n}__fasting_cgm_0600" for n in range(1, 15)]
    write_csv(
        _frame([r["request"] | r["fbs"] for r in records], fbs_columns, text),
        deliver / f"{PREFIX}_FBS_24H_D1-14_Results.csv",
    )

    def daily_sheets():
        for n in range(1, 15):
            columns = result_columns(request_columns, daily=True)
            yield (
                f"Day {n}",
                _excel_parts(
                    _frame(
                        [r["request"] | r["tables"].get(f"cgm_day_{n}", {}) for r in records],
                        columns,
                        text,
                    )
                ),
            )

    write_workbook(deliver / f"{PREFIX}_Mode0_Daily_D1-14.xlsx", daily_sheets())
    status = pd.DataFrame(
        [
            {
                **{c: r["request"].get(c, "") for c in request_columns},
                **{k: r[k] for k in ("computation_status", "error_code", "error_message")},
            }
            for r in records
        ]
    )
    write_csv(status, root / "patient_status.csv")
    return records


def run_drq_batch(
    request_path,
    config_path,
    output_root,
    run_id,
    workers=4,
    resume=False,
    *,
    extended=False,
    prefix=PREFIX,
):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) or workers < 1:
        raise CalculationError("ERROR03", "Invalid run ID or worker count", "batch")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", prefix):
        raise CalculationError("ERROR03", "Invalid delivery filename prefix", "batch")
    request_content = request_path.read_bytes()
    config_content = config_path.read_bytes()
    request = read_request(request_path, content=request_content)
    if request.empty:
        raise CalculationError("ERROR03", "Empty request list", "batch")
    request_columns = (
        list(PUMP_PREFIX)
        + ["analysis_id"]
        + [c for c in request if c not in (*PUMP_PREFIX, "analysis_id", "request_row")]
    )
    result_columns(request_columns, daily=True)
    config, _ = load_config(config_path, content=config_content)
    provenance = _code_provenance()
    inputs = {
        "request": hashlib.sha256(request_content).hexdigest(),
        "config": hashlib.sha256(config_content).hexdigest(),
    }
    signature = {
        "inputs": inputs,
        "code_sha256": provenance["code_sha256"],
        "extended": extended,
        "prefix": prefix,
    }
    root = output_root / run_id
    state = {
        "run_id": run_id,
        "status": "RUNNING",
        "patient_count": len(request),
        "formal_release": False,
    }
    if root.exists():
        if not resume:
            raise FileExistsError(root)
        saved = json.loads((root / "resume_signature.json").read_text(encoding="utf-8"))
        if saved != signature:
            raise CalculationError(
                "ERROR03", "Resume requires unchanged request, config and source", "batch"
            )
        previous = json.loads((root / "run_state.json").read_text(encoding="utf-8"))
        if previous["status"] == "COMPLETED_RESEARCH":
            return root
    else:
        root.mkdir(parents=True)
        (root / "audit").mkdir()
        _save(root / "resume_signature.json", signature)
        (root / "request.csv").write_bytes(request_content)
        (root / "config.yaml").write_bytes(config_content)
    _save(root / "run_state.json", state)
    try:
        tasks = []
        for i, row in enumerate(request.to_dict("records"), 1):
            path = root / "audit" / f"request_{i:04d}.json"
            if path.exists():
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved["request"] != row:
                    raise ValueError("Patient resume identity mismatch")
                if "source_sha256" in saved:
                    from cgm_library.io.reader import locate_source

                    source, _ = locate_source(row, config)
                    if _sha256(source) != saved["source_sha256"]:
                        raise ValueError("Original device file changed during resume")
                continue
            tasks.append((i, row, config, path, extended))
        if workers == 1:
            for i, outcome in map(_worker, tasks):
                print(f"Patient {i}/{len(request)} {outcome}", flush=True)
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for n, (i, outcome) in enumerate(pool.map(_worker, tasks, chunksize=1), 1):
                    if n % 25 == 0 or n == len(tasks):
                        print(f"Completed {n}/{len(tasks)} pending patients", flush=True)
        delivery_stats = {}
        if extended:
            from cgm_library.workflows.delivery import export_delivery

            records, delivery_stats = export_delivery(root, request, prefix)
        else:
            records = _export(root, request, request_columns)
        state["status"] = "COMPLETED_RESEARCH"
        state["completed_patients"] = len(records)
        state["patient_status_counts"] = dict(Counter(r["computation_status"] for r in records))
        _save(root / "run_state.json", state)
        manifest = {
            **state,
            **provenance,
            "input_sha256": inputs,
            "effective_config": config.snapshot(),
            "created_at_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "pending_rule_gates": ["MAGE_REFERENCE_VALIDATION"],
            "table_decimal_places": 4,
            "delivery_revision": "261112" if extended else "261110",
            "delivery_prefix": prefix,
            "delivery_statistics": delivery_stats,
            "delivery_files": sorted(p.name for p in (root / "results").iterdir()),
            "outputs_sha256": {
                p.relative_to(root).as_posix(): _sha256(p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and p.name not in ("manifest.json", "manifest.sha256")
            },
        }
        _save(root / "manifest.json", manifest)
        (root / "manifest.sha256").write_text(
            _sha256(root / "manifest.json") + "  manifest.json\n", encoding="ascii"
        )
    except Exception, KeyboardInterrupt:
        state["status"] = "ABORTED"
        _save(root / "run_state.json", state)
        raise
    return root

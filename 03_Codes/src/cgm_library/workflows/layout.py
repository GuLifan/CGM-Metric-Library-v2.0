"""Revise presentation from immutable calculation evidence, without recalculating CGM metrics."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cgm_library.io.reader import read_request
from cgm_library.studies.delivery import LAYOUT_VERSION
from cgm_library.workflows.batch import _code_provenance, _sha256
from cgm_library.workflows.delivery import export_delivery


def resolve_audit_root(root, manifest):
    root = Path(root).resolve()
    reference = manifest.get("calculation_reference")
    if not reference:
        return root / "audit"
    source = (root / reference["relative_run_path"]).resolve()
    if _sha256(source / "manifest.json") != reference["manifest_sha256"]:
        raise ValueError("Referenced calculation manifest changed")
    return source / "audit"


def reexport_delivery(source_run, output_root, run_id, prefix):
    """Create a fresh delivery revision and retain the source run and original ZIP."""
    source_run, output_root = Path(source_run).resolve(), Path(output_root).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid layout run ID")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", prefix):
        raise ValueError("Invalid delivery prefix")
    source_bytes = (source_run / "manifest.json").read_bytes()
    source = json.loads(source_bytes)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if source_sha != (source_run / "manifest.sha256").read_text(encoding="ascii").split()[0]:
        raise ValueError("Source manifest checksum mismatch")
    if source.get("delivery_revision") != "261112" or source["status"] != "COMPLETED_RESEARCH":
        raise ValueError("A completed 261112 calculation is required")
    audit = resolve_audit_root(source_run, source)
    calculation_bytes = (audit.parent / "manifest.json").read_bytes()
    calculation = json.loads(calculation_bytes)
    for name, key in (("request.csv", "request"), ("config.yaml", "config")):
        if _sha256(source_run / name) != source["input_sha256"][key]:
            raise ValueError(f"Source input changed: {name}")
    # Hash the actual calculation evidence before relying on its saved scalar precision.
    request = read_request(source_run / "request.csv")
    if len(request) != source["patient_count"]:
        raise ValueError("Source cohort size changed")
    for i in range(1, len(request) + 1):
        name = f"request_{i:04d}.json"
        expected = calculation["outputs_sha256"]["audit/" + name]
        if _sha256(audit / name) != expected:
            raise ValueError(f"Changed calculation evidence: {name}")
    root = output_root / run_id
    root.mkdir(parents=True, exist_ok=False)
    for name in ("request.csv", "config.yaml"):
        (root / name).write_bytes((source_run / name).read_bytes())
    (root / "calculation_manifest.json").write_bytes(calculation_bytes)
    state = {
        "run_id": run_id,
        "status": "RUNNING",
        "patient_count": len(request),
        "formal_release": False,
    }

    def save_state():
        (root / "run_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    save_state()
    try:
        records, statistics = export_delivery(root, request, prefix, audit_root=audit)
        state.update(
            status="COMPLETED_RESEARCH",
            completed_patients=len(records),
            patient_status_counts=dict(Counter(r["computation_status"] for r in records)),
        )
        if state["patient_status_counts"] != source["patient_status_counts"]:
            raise ValueError("Layout revision changed patient outcomes")
        save_state()
        manifest = {
            **state,
            **_code_provenance(),
            "delivery_revision": "261112",
            "delivery_layout_version": LAYOUT_VERSION,
            "delivery_prefix": prefix,
            "delivery_statistics": statistics,
            "input_sha256": source["input_sha256"],
            "effective_config": source["effective_config"],
            "pending_rule_gates": source["pending_rule_gates"],
            "table_decimal_places": 4,
            "created_at_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "calculation_reference": {
                "relative_run_path": Path(os.path.relpath(audit.parent, root)).as_posix(),
                "manifest_sha256": _sha256(audit.parent / "manifest.json"),
                "source_run_id": calculation["run_id"],
                "published_source_commit": calculation.get("published_source_commit"),
                "calculation_code_sha256": calculation.get("code_sha256"),
            },
            "delivery_files": sorted(p.name for p in (root / "results").iterdir()),
            "outputs_sha256": {
                p.relative_to(root).as_posix(): _sha256(p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and p.name not in ("manifest.json", "manifest.sha256")
            },
        }
        data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (root / "manifest.json").write_bytes(data)
        (root / "manifest.sha256").write_text(
            hashlib.sha256(data).hexdigest() + "  manifest.json\n", encoding="ascii"
        )
    except BaseException:
        state["status"] = "ABORTED"
        save_state()
        raise
    return root

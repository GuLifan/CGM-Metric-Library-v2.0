"""Compare a revised real cohort against the submitted ZIP without exposing patient IDs."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook
from validate_delivery import same

from cgm_library.io.pump_request import PUMP_PREFIX
from cgm_library.studies.drq import GROUP_FILES


def compare(archive, root, previous_run):
    root, previous_run = Path(root), Path(previous_run)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    prior = json.loads((previous_run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["input_sha256"] == prior["input_sha256"]
    prefix = manifest["delivery_prefix"]
    counts, differences = Counter(), Counter()

    def local(value):
        if value is None or value == "":
            return ""
        stamp = pd.Timestamp(value)
        return stamp.tz_localize(None) if stamp.tzinfo is not None else stamp

    def check_rows(before, after, label, *, skip_rows=()):
        assert len(before) == len(after)
        for i, (a, b) in enumerate(zip(before, after, strict=True), 1):
            if i in skip_rows:
                continue
            assert set(a) == set(b), label
            for key in a:
                if key in ("window_start", "window_end"):
                    equal = local(a[key]) == local(b[key])
                else:
                    equal = same(a[key], b[key])
                if not equal:
                    differences[label, key] += 1
                counts[label + "_cells"] += 1

    def file_rows(path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    with ZipFile(archive) as z:

        def old_rows(suffix):
            path = next(n for n in z.namelist() if n.endswith(suffix))
            return list(csv.DictReader(io.StringIO(z.read(path).decode("utf-8-sig"))))

        old_status = old_rows("2204_PatientStatus.csv")
        new_status = file_rows(root / "results/2204_PatientStatus.csv")
        for a, b in zip(old_status, new_status, strict=True):
            assert all(a[k] == b[k] for k in (*PUMP_PREFIX, "computation_status", "error_code"))
        for suffix in GROUP_FILES.values():
            before = old_rows(suffix)
            after = file_rows(root / "results" / f"{prefix}_{suffix}")
            check_rows(before, after, "mode")
        check_rows(
            old_rows("FBS_24H_D1-14_Results.csv"),
            file_rows(root / "results" / f"{prefix}_FBS_24H_D1-14_Results.csv"),
            "fbs",
        )
        name = next(n for n in z.namelist() if n.endswith("NewMetric_Summary.xlsx"))
        book = load_workbook(io.BytesIO(z.read(name)), read_only=True, data_only=True)
        it = book["患者总览"].values
        headers = next(it)
        overview = [dict(zip(headers, row, strict=True)) for row in it]
        book.close()
        changed_requests = [
            i
            for i, (a, b) in enumerate(zip(overview, new_status, strict=True), 1)
            if a["computation_status"] != b["computation_status"]
        ]
        check_rows(
            old_rows("NewMetric_Results.csv"),
            file_rows(root / "results" / f"{prefix}_NewMetric_Results.csv"),
            "newmetric",
            skip_rows=changed_requests,
        )
        old_name = next(n for n in z.namelist() if n.endswith("Mode0_Daily_D1-14.xlsx"))
        old_book = load_workbook(io.BytesIO(z.read(old_name)), read_only=True, data_only=True)
        new_book = load_workbook(
            root / "results" / f"{prefix}_Mode0_Daily_D1-14.xlsx", read_only=True, data_only=True
        )
        assert old_book.sheetnames == new_book.sheetnames
        for a, b in zip(old_book, new_book, strict=True):
            ai, bi = a.values, b.values
            ah, bh = next(ai), next(bi)
            assert ah == bh
            check_rows(
                [dict(zip(ah, r, strict=True)) for r in ai],
                [dict(zip(bh, r, strict=True)) for r in bi],
                "cgm_daily",
            )
        old_book.close()
        new_book.close()
    source_mismatches = []
    for i in range(1, manifest["patient_count"] + 1):
        a = json.loads(
            (previous_run / "audit" / f"request_{i:04d}.json").read_text(encoding="utf-8")
        )
        b = json.loads((root / "audit" / f"request_{i:04d}.json").read_text(encoding="utf-8"))
        if a.get("source_sha256") != b.get("source_sha256"):
            source_mismatches.append(i)
        if a.get("source_sha256"):
            counts["source_hashes_checked"] += 1
    report = dict(counts) | {
        "patient_count": manifest["patient_count"],
        "newmetric_status_changed_requests": changed_requests,
        "cell_differences": {f"{k[0]}/{k[1]}": v for k, v in differences.items()},
        "source_hash_changed_requests": source_mismatches,
    }
    assert not differences and not source_mismatches, report
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("previous_run", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.archive, args.run, args.previous_run)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report))

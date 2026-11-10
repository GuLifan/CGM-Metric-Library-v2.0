"""Verify the complete DRQ delivery against per-patient computation evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from cgm_library.io.tables import four_places
from cgm_library.studies.drq import EVENT_FIELDS, GROUP_FILES, PREFIX

csv.field_size_limit(2**31 - 1)


def text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


def validate(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = (root / "manifest.sha256").read_text(encoding="ascii").split()[0]
    assert hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() == expected
    assert manifest["status"] == "COMPLETED_RESEARCH" and manifest["formal_release"] is False
    for name, digest in manifest["outputs_sha256"].items():
        path = (root / name).resolve()
        assert root.resolve() in path.parents
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == digest
    with (root / "request.csv").open(encoding="utf-8-sig", newline="") as stream:
        request = list(csv.DictReader(stream))
    identities = [r["analysis_id"] for r in request]
    assert len(identities) == len(set(identities)) == manifest["patient_count"]
    result_files = {p.name for p in (root / "results").iterdir()}
    expected = {f"{PREFIX}_{v}" for v in GROUP_FILES.values()} | {
        f"{PREFIX}_FBS_24H_D1-14_Results.csv",
        f"{PREFIX}_Mode0_Daily_D1-14.xlsx",
    }
    assert result_files == expected and len(expected) == 15
    audits = [
        json.loads((root / "audit" / f"request_{i:04d}.json").read_text(encoding="utf-8"))
        for i in range(1, len(request) + 1)
    ]
    assert [a["request"]["analysis_id"] for a in audits] == identities

    def check_records(path, window):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            records = list(reader)
            assert list(reader.fieldnames[:7]) == [
                "住院号",
                "出院日期",
                "入院日期",
                "设备文件名",
                "胰岛素泵开始时间",
                "胰岛素泵停止时间",
                "analysis_id",
            ]
        assert len(records) == len(request)
        for req, audit, record in zip(request, audits, records, strict=True):
            assert all(record[k] == v for k, v in req.items() if k in record)
            row = audit["fbs"] if window == "fbs" else audit["tables"].get(window, {})
            for k, v in record.items():
                if k not in req:
                    assert v == text(row.get(k)), (path.name, k, req["analysis_id"])
            for key in EVENT_FIELDS:
                count = row.get(key + "_n")
                if count is not None:
                    assert int(count) == len(json.loads(row[key + "_events_json"]))
            if row.get("TIR_pct") is not None:
                assert (
                    abs(sum(float(row[k]) for k in ("TIR_pct", "TAR_pct", "TBR_pct")) - 100)
                    <= 0.000151
                )
                assert (
                    abs(
                        sum(float(row[k]) for k in ("TIR_minutes", "TAR_minutes", "TBR_minutes"))
                        - float(audit["tables"][window]["valid_minutes"])
                    )
                    <= 0.000201
                )
                assert 0 <= float(row["GRI"]) <= 100
                previous = 0
                for n in range(9):
                    count = int(row[f"hypo_cond_lt3p{n}_n"])
                    assert previous <= count <= int(row["hypo_episode_lt3p9_n"])
                    previous = count
            if window != "fbs" and audit["audit"].get(window, {}).get("sufficient_flag"):
                a = audit["audit"][window]
                start = pd.Timestamp(a["window_start"])
                end = pd.Timestamp(a["window_end"])
                span = (end - start).total_seconds() / 60
                assert span > 0 and 70 <= float(a["coverage_pct"]) <= 100
                assert a["expected_points"] == math.ceil(span / 5)
                assert 0 < a["valid_points"] <= a["expected_points"]
        return len(records)

    for window, suffix in GROUP_FILES.items():
        check_records(root / "results" / f"{PREFIX}_{suffix}", window)
    check_records(root / "results" / f"{PREFIX}_FBS_24H_D1-14_Results.csv", "fbs")
    book = load_workbook(root / "results" / f"{PREFIX}_Mode0_Daily_D1-14.xlsx", read_only=True)
    assert book.sheetnames == [f"Day {n}" for n in range(1, 15)]
    cell_count = 0
    for number, sheet in enumerate(book, 1):
        rows = iter(sheet)
        columns = [cell.value for cell in next(rows)]
        row_count = 0
        for row_count, (cells, req, audit) in enumerate(zip(rows, request, audits, strict=True), 1):
            actual = {key: cell.value for key, cell in zip(columns, cells, strict=True)}
            desired = req | audit["tables"].get(f"cgm_day_{number}", {})
            for cell, column in zip(cells, columns, strict=True):
                if cell.value is not None:
                    assert cell.font.name == "Times New Roman"
                if "__part" in column:
                    continue
                target = desired.get(column)
                if column.endswith("_json"):
                    parts = [column] + sorted(
                        [c for c in columns if c.startswith(column + "__part")],
                        key=lambda c: int(c.rsplit("__part", 1)[1]),
                    )
                    assert "".join(str(actual[c] or "") for c in parts) == text(target)
                elif column in req or column in ("window_start", "window_end"):
                    assert text(cell.value) == text(target)
                elif target is None:
                    assert cell.value is None
                else:
                    assert four_places(float(cell.value)) == four_places(float(target))
                    if cell.number_format == "0.0000":
                        assert float(four_places(cell.value)) == cell.value
                cell_count += 1
        assert row_count == len(request)
    book.close()
    return {
        "patient_count": len(request),
        "delivery_file_count": 15,
        "daily_cells_checked": cell_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.output)))

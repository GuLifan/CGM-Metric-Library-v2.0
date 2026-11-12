"""Check revised delivery cells, window boundaries, fonts, events and asset hashes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from cgm_library.contracts.fields import ASSETS
from cgm_library.events.engine import CONFIRMED_RULES
from cgm_library.io.pump_request import PUMP_PREFIX
from cgm_library.io.reader import parse_anchor
from cgm_library.studies.delivery import PERIODS, WINDOW_NAMES, mode_columns, scalar_columns
from cgm_library.studies.drq import GROUP_FILES
from cgm_library.workflows.delivery import TEXT_COLUMNS
from cgm_library.workflows.delivery import display as delivery_display


def display(column, value):
    # A CSV overview has empty strings where the source audit had null timestamps.
    return "" if value == "" else delivery_display(column, value)


def same(a, b):
    a, b = ("" if v is None else str(v) for v in (a, b))
    if a == b:
        return True
    try:
        return Decimal(a) == Decimal(b)
    except InvalidOperation:
        return False


def validate(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["delivery_revision"] == "261112"
    digest = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    assert (root / "manifest.sha256").read_text(encoding="ascii").split()[0] == digest
    for name, expected in manifest["outputs_sha256"].items():
        path = (root / name).resolve()
        assert root in path.parents
        with path.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == expected, name
    prefix = manifest["delivery_prefix"]
    out = root / "results"
    with (root / "request.csv").open(encoding="utf-8-sig", newline="") as handle:
        requests = list(csv.DictReader(handle))
    assert len(requests) == manifest["patient_count"]
    assert {p.name for p in out.iterdir()} == set(manifest["delivery_files"])
    by_identity = {tuple(r[k] for k in PUMP_PREFIX): i for i, r in enumerate(requests, 1)}
    assert len(by_identity) == len(requests)
    event_expected, conditional_expected, after_expected = Counter(), Counter(), {}
    quality_expected = {}
    checked = Counter()

    def identity(row):
        return tuple(row[k] for k in PUMP_PREFIX)

    def check(row, desired, header, label):
        for key in header:
            assert same(row.get(key), display(key, desired.get(key))), (label, key)
            checked["scalar_cells"] += 1

    with ExitStack() as stack:
        readers = {}
        for path in out.glob("*.csv"):
            reader = csv.DictReader(
                stack.enter_context(path.open(encoding="utf-8-sig", newline=""))
            )
            assert "analysis_id" not in reader.fieldnames, path.name
            if path.name not in ("2204_PatientStatus.csv", "2204_RequestList.csv"):
                assert list(reader.fieldnames[:6]) == list(PUMP_PREFIX), path.name
            readers[path.name] = reader
        book = load_workbook(out / f"{prefix}_Mode0_Daily_D1-14.xlsx", read_only=True)
        stack.callback(book.close)
        daily_readers = {}
        assert book.sheetnames == [f"Day {n}" for n in range(1, 15)]
        for n, sheet in enumerate(book, 1):
            iterator = sheet.iter_rows()
            cells = next(iterator)
            headers = [c.value for c in cells]
            assert headers == mode_columns() + ["MODD_vs_previous_cgm_day_mmol_L"]
            assert all(c.font.name == "Times New Roman" for c in cells)
            daily_readers[n] = headers, iterator
        summary = load_workbook(out / f"{prefix}_NewMetric_Summary.xlsx", read_only=True)
        stack.callback(summary.close)
        summary_readers = {}
        for name in ("患者总览", "未计算病例", "Full7", "Sparse5"):
            it = summary[name].iter_rows()
            headers = [c.value for c in next(it)]
            assert "analysis_id" not in headers
            summary_readers[name] = headers, it

        def check_sheet(reader, expected, label):
            headers, iterator = reader
            cells = next(iterator)
            for key, cell in zip(headers, cells, strict=True):
                if cell.value is not None:
                    assert cell.font.name == "Times New Roman", label
                    if cell.number_format == "0.0000":
                        assert (
                            float(Decimal(str(cell.value)).quantize(Decimal("0.0001")))
                            == cell.value
                        )
                assert same(cell.value, display(key, expected.get(key))), (label, key)
                checked["excel_cells"] += 1

        for i, req in enumerate(requests, 1):
            record = json.loads(
                (root / "audit" / f"request_{i:04d}.json").read_text(encoding="utf-8")
            )
            ident = tuple(req[k] for k in PUMP_PREFIX)
            assert all(record["request"][k] == req[k] for k in PUMP_PREFIX)
            for window, suffix in GROUP_FILES.items():
                reader = readers[f"{prefix}_{suffix}"]
                assert reader.fieldnames == mode_columns()
                check(
                    next(reader), req | record["tables"].get(window, {}), reader.fieldnames, suffix
                )
            for n, reader in daily_readers.items():
                check_sheet(reader, req | record["tables"].get(f"cgm_day_{n}", {}), f"Day {n}")
            scalar = req.copy()
            for window in WINDOW_NAMES:
                scalar.update(
                    {f"{window}__{k}": v for k, v in record["tables"].get(window, {}).items()}
                )
            for name, title in (("full7", "Full7"), ("sparse5", "Sparse5")):
                features = record.get("features", {}).get(name, {})
                scalar.update({f"{title}__{k}": v for k, v in features.items()})
                if record["computation_status"] == "COMPUTED":
                    assert set(ASSETS[name].fields) <= set(features)
                    check_sheet(summary_readers[title], req | features, title)
            reader = readers[f"{prefix}_NewMetric_Results.csv"]
            assert reader.fieldnames == scalar_columns() and len(reader.fieldnames) == 390
            check(next(reader), scalar, reader.fieldnames, "NewMetric")
            reader = readers[f"{prefix}_FBS_24H_D1-14_Results.csv"]
            check(next(reader), req | record["fbs"], reader.fieldnames, "FBS")
            status = next(readers["2204_PatientStatus.csv"])
            check(status, req | record, list(status), "status")
            overview = next(readers[f"{prefix}_Patient_Summary.csv"])
            assert overview["computation_status"] == record["computation_status"]
            check_sheet(summary_readers["患者总览"], overview, "overview")
            if record["computation_status"] != "COMPUTED":
                check_sheet(summary_readers["未计算病例"], status, "uncomputed")
            for window, row in record["tables"].items():
                if window.startswith("post_discharge_day_"):
                    n = int(window.removeprefix("post_discharge_day_"))
                    start, end = (pd.Timestamp(row[k]) for k in ("window_start", "window_end"))
                    discharge = parse_anchor(req["出院日期"])
                    assert start == discharge + pd.Timedelta(days=n - 1)
                    assert end - start == pd.Timedelta(days=1)
                    assert float(row["window_minutes"]) == 1440
                    assert (
                        abs(float(row["coverage_pct"]) - float(row["valid_minutes"]) / 1440 * 100)
                        < 0.00006
                    )
                    after_expected[ident, n] = row
                for period in ("all", *PERIODS):
                    head = "" if period == "all" else period + "__"
                    qualified = bool(row.get(head + "sufficient_flag"))
                    reason = (
                        ""
                        if qualified
                        else (
                            record["error_code"]
                            or record["audit"].get(window, {}).get("reason")
                            or "COVERAGE_BELOW_THRESHOLD"
                        )
                    )
                    quality_expected[ident, window, period] = (
                        row.get(head + "coverage_pct"),
                        qualified,
                        reason,
                    )
                    if not row.get(head + "sufficient_flag"):
                        continue
                    for rule in CONFIRMED_RULES:
                        if not rule.high:
                            event_expected[ident, window, period, rule.event_type] = int(
                                row[head + rule.event_type + "_n"]
                            )
                    if period == "all":
                        for n in range(30, 39):
                            conditional_expected[ident, window, n] = int(
                                row[f"hypo_cond_lt{n // 10}p{n % 10}_n"]
                            )
            if not record["tables"]:
                for day in range(1, 8):
                    for period in ("all", *PERIODS):
                        quality_expected[ident, f"post_discharge_day_{day}", period] = (
                            None,
                            False,
                            record["error_code"],
                        )
            if i % 250 == 0:
                print(f"Verified patient tables {i}/{len(requests)}", flush=True)
        for reader in readers.values():
            if reader.fieldnames and "post_discharge_day" not in reader.fieldnames:
                # Request is a standalone identity table, not consumed above.
                if reader is readers["2204_RequestList.csv"]:
                    assert [identity(r) for r in reader] == [identity(r) for r in requests]
                else:
                    assert next(reader, None) is None
        for _, it in list(daily_readers.values()) + list(summary_readers.values()):
            assert next(it, None) is None

    actual_events, actual_conditions = Counter(), Counter()
    with (out / f"{prefix}_Hypoglycemia_Events.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            ident, window, period = identity(row), row["window_name"], row["period"]
            actual_events[ident, window, period, row["event_type"]] += 1
            start, end = pd.Timestamp(row["event_start"]), pd.Timestamp(row["event_end"])
            assert start.tzinfo is None and end.tzinfo is None
            assert abs((end - start).total_seconds() / 60 - float(row["duration_min"])) < 0.00006
            assert 0 < float(row["condition_minutes"]) <= float(row["duration_min"]) + 0.0001
            if row["event_type"] == "hypo_episode_lt3p9" and period == "all":
                for value in filter(None, row["hypo_cond_thresholds"].split("|")):
                    actual_conditions[ident, window, round(float(value) * 10)] += 1
            checked["event_rows"] += 1
    assert actual_events == +event_expected, "Event details disagree with window counts"
    assert actual_conditions == +conditional_expected, "Conditional event membership changed"
    quality_seen = set()
    with (out / f"{prefix}_Window_Quality.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = identity(row), row["window_name"], row["period"]
            assert key not in quality_seen
            quality_seen.add(key)
            coverage, qualified, reason = quality_expected[key]
            assert same(row["coverage_pct"], coverage)
            assert same(row["sufficient_flag"], qualified)
            assert row["metric_reason"] == reason
            if qualified:
                assert 70 <= float(row["coverage_pct"]) <= 100
            checked["quality_rows"] += 1
    assert quality_seen == set(quality_expected)
    days_seen = {}
    with (out / f"{prefix}_AfterDischarge_Daily_Results.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            ident, day = identity(row), int(row["post_discharge_day"])
            days_seen.setdefault(ident, []).append(day)
            desired = after_expected.get((ident, day))
            if desired:
                for key in row:
                    if key in desired:
                        assert same(row[key], display(key, desired[key])), ("after_discharge", key)
            else:
                assert row["computation_status"] == "DATA_ERROR"
                assert row["MEAN"] == "" and row["metric_reason"]
            checked["after_discharge_rows"] += 1
    assert set(days_seen) == set(by_identity)
    assert all(
        days == list(range(1, max(days) + 1)) and max(days) >= 7 for days in days_seen.values()
    )
    for path in out.glob("*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                for key, value in row.items():
                    if key not in TEXT_COLUMNS and re.fullmatch(r"-?\d+\.\d+", value or ""):
                        assert len(value.rsplit(".", 1)[1]) == 4, (path.name, key)
    assert (
        checked["after_discharge_rows"] == manifest["delivery_statistics"]["after_discharge_rows"]
    )
    assert checked["event_rows"] == manifest["delivery_statistics"].get(
        "hypoglycemia_event_rows", 0
    )
    return dict(checked) | {
        "patient_count": len(requests),
        "delivery_file_count": len(manifest["delivery_files"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.output)))

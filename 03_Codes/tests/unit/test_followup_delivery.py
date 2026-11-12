"""Follow-up days, cross-entry eligibility and readable event delivery contracts."""

import csv
import runpy
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from test_drq_delivery import inputs

from cgm_library.contracts.schema import load_config
from cgm_library.io.reader import read_request
from cgm_library.studies.delivery import AFTER_DAY_COLUMNS, EVENT_COLUMNS
from cgm_library.studies.drq import post_discharge_windows
from cgm_library.workflows.drq_batch import run_drq_batch
from cgm_library.workflows.drq_patient import calculate_drq_patient
from cgm_library.workflows.patient import calculate_patient_partial


def test_followup_days_keep_discharge_clock_and_full_last_day():
    discharge = pd.Timestamp("2026-01-01 14:37:21", tz="Asia/Shanghai")
    day = pd.Timedelta(days=1)
    assert len(post_discharge_windows(discharge, discharge + 7 * day)) == 7
    windows = post_discharge_windows(discharge, discharge + 7 * day + pd.Timedelta(minutes=1))
    assert len(windows) == 8
    assert windows["post_discharge_day_8"] == (discharge + 7 * day, discharge + 8 * day)


def test_old_and_drq_entries_both_accept_post_discharge_only_recording(tmp_path):
    request, config_path = inputs(tmp_path, discharge="2025-12-31 12:00:00", stop="")
    row, config = read_request(request).iloc[0].to_dict(), load_config(config_path)[0]
    old = calculate_patient_partial(row, config)
    new = calculate_drq_patient(row, config, extended=True)
    assert old.window_rows.set_index("window_name").loc["all_record", "MEAN"] > 0
    assert np.isnan(old.window_rows.set_index("window_name").loc["inpatient", "MEAN"])
    assert new["warning_codes"] == "CGM_START_AT_OR_AFTER_DISCHARGE"
    assert np.isnan(new["features"]["sparse5"]["sparse_mean_cgm_d1"])
    assert old.sparse5["sparse_d1_valid_n"] == 0
    assert old.sparse_targets.reason.eq("TARGET_AFTER_DISCHARGE").sum() == 8
    d1, d2 = (new["tables"][f"post_discharge_day_{n}"] for n in (1, 2))
    assert d1["window_start"].hour == d2["window_start"].hour == 12
    assert d1["window_minutes"] == d2["window_minutes"] == 1440
    assert d1["coverage_pct"] < 70 and np.isnan(d1["MEAN"])
    assert d2["coverage_pct"] == 100
    assert np.isnan(d2["MODD_vs_previous_discharge_day_mmol_L"])
    assert new["tables"]["post_discharge_day_3"]["MODD_vs_previous_discharge_day_mmol_L"] == 0


def test_revised_batch_keeps_ids_readable_events_and_same_batch_features(tmp_path):
    request, config = inputs(tmp_path)
    root = run_drq_batch(
        request,
        config,
        tmp_path,
        "revised",
        workers=1,
        extended=True,
        prefix="DRQ261112_CML2.0_TEST",
    )
    out = root / "results"

    def read(suffix):
        with next(out.glob("*" + suffix)).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return reader.fieldnames, list(reader)

    headers, rows = read("AfterDischarge_Daily_Results.csv")
    assert headers == AFTER_DAY_COLUMNS and len(rows) == 7
    assert rows[0]["window_start"] == "2026-01-03 08:00:00"
    assert rows[0]["MEAN"] == "6.0000"
    assert rows[1]["MODD_vs_previous_discharge_day_mmol_L"] == "0.0000"
    assert rows[2]["sufficient_flag"] == "False" and rows[2]["MEAN"] == ""
    assert all(r["住院号"] == "0001" for r in rows)
    headers, events = read("Hypoglycemia_Events.csv")
    assert headers == EVENT_COLUMNS and events
    event = next(
        r
        for r in events
        if r["window_name"] == "all_record"
        and r["period"] == "all"
        and r["event_type"] == "hypo_episode_lt3p9"
    )
    assert event["event_start"] == "2026-01-01 10:00:00"
    assert event["event_end"] == "2026-01-01 10:15:00"
    assert event["duration_min"] == "15.0000" and event["nadir_mmol_L"] == "2.8000"
    assert "+08:00" not in "".join(event.values())
    assert Counter(
        e["event_type"] for e in events if e["window_name"] == "all_record" and e["period"] == "all"
    ) == {
        "hypo_episode_lt3p9": 1,
        "level2_period_lt3p0": 1,
    }
    headers, scalars = read("NewMetric_Results.csv")
    assert len(headers) == 390 and scalars[0]["Full7__mean_pump_d1"] == "6.0000"
    for path in out.glob("*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            assert "analysis_id" not in next(csv.reader(handle))
    book = load_workbook(next(out.glob("*NewMetric_Summary.xlsx")), read_only=True)
    overview = list(book["患者总览"].values)
    assert overview[1][overview[0].index("computation_status")] == "COMPUTED"
    assert all(cell.font.name == "Times New Roman" for row in book["Full7"] for cell in row)
    book.close()
    validate = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "tools/validate_delivery.py")
    )["validate"]
    assert validate(root)["patient_count"] == 1


def test_failed_patient_retains_seven_followup_rows_with_stable_feature_schema(tmp_path):
    request, config = inputs(tmp_path, discharge="invalid-time")
    root = run_drq_batch(
        request, config, tmp_path, "failed", workers=1, extended=True, prefix="FAILED"
    )
    with (root / "results/FAILED_AfterDischarge_Daily_Results.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 7 and all(r["metric_reason"] == "ERROR04" for r in rows)
    assert all(r["window_start"] == "" and r["MEAN"] == "" for r in rows)
    book = load_workbook(root / "results/FAILED_NewMetric_Summary.xlsx", read_only=True)
    rows = list(book["Full7"].values)
    assert len(rows) == 1 and "mean_pump_d1" in rows[0]
    book.close()
    validate = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "tools/validate_delivery.py")
    )["validate"]
    assert validate(root)["patient_count"] == 1


def test_single_conditional_threshold_is_a_category_not_a_decimal_measurement(tmp_path):
    request, config = inputs(tmp_path)
    source = tmp_path / "source/sample.csv"
    data = pd.read_csv(source)
    data.loc[24:26, "v"] = 3.75
    data.to_csv(source, index=False)
    root = run_drq_batch(
        request, config, tmp_path, "one_threshold", workers=1, extended=True, prefix="ONE_THRESHOLD"
    )
    with (root / "results/ONE_THRESHOLD_Hypoglycemia_Events.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        events = list(csv.DictReader(handle))
    assert events and all(r["hypo_cond_thresholds"] == "3.8" for r in events)
    validate = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "tools/validate_delivery.py")
    )["validate"]
    assert validate(root)["patient_count"] == 1

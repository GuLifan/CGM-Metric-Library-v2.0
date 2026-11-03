"""只用合成数据验证输入契约和原始读数保真清洗。"""

from __future__ import annotations

import csv

import pandas as pd
import pytest
from openpyxl import Workbook

from cgm_library.contracts.schema import CalculationError, RunConfig, SourceFolder
from cgm_library.io.reader import locate_source, parse_anchor, read_cgm, read_request
from cgm_library.qc.raw import clean_observations, raw_interval_distribution

PREFIX = [
    "住院号",
    "出院日期",
    "入院日期",
    "设备文件名",
    "胰岛素泵开始时间",
    "胰岛素泵停止时间",
]


def test_request_contract_preserves_extra_fields_and_identifiers(tmp_path):
    path = tmp_path / "synthetic_request.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([*PREFIX, "analysis_id", "备注"])
        writer.writerow(
            ["0007", "2026-01-05", "2026-01-01", "sample.xlsx", "2026-01-01", "", "A7", "保留"]
        )
    result = read_request(path)
    assert list(result.columns[:6]) == PREFIX
    assert result.loc[0, "住院号"] == "0007"
    assert result.loc[0, "备注"] == "保留"
    assert result.loc[0, "request_row"] == 2
    assert parse_anchor("2026-01-01").hour == 0
    assert parse_anchor("2026-01-01", pump_start=True).hour == 12

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([*PREFIX[:4], "其他列", *PREFIX[4:]])
        writer.writerow(["0007", "2026-01-05", "2026-01-01", "sample.xlsx", "X", "2026-01-01", ""])
    with pytest.raises(CalculationError, match="前六列"):
        read_request(path)


def test_source_lookup_is_exact_and_batch_selection_is_unique(tmp_path):
    source = tmp_path / "batch"
    source.mkdir()
    (source / "sample.xlsx").touch()
    config = RunConfig((SourceFolder(source, 5, "mmol/L"),))
    path, chosen = locate_source({"出院日期": "2026-01-05", "设备文件名": "sample"}, config)
    assert path.name == "sample.xlsx" and chosen.interval_min == 5
    with pytest.raises(CalculationError, match="未找到"):
        locate_source({"出院日期": "2026-01-05", "设备文件名": "sam"}, config)
    with pytest.raises(CalculationError, match="单一文件名"):
        locate_source({"出院日期": "2026-01-05", "设备文件名": "../sample.xlsx"}, config)


def test_excel_reader_accepts_known_schema_and_rejects_unknown_columns(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    pd.DataFrame({"t": ["2026-01-01 00:00"], "v": ["5.6"]}).to_excel(path, index=False)
    result = read_cgm(path, "mmol/L")
    assert result.loc[0, "glucose_raw"] == "5.6"
    assert result.loc[0, "source_row"] == 2
    pd.DataFrame({"time": ["2026-01-01"], "value": ["5.6"]}).to_excel(path, index=False)
    with pytest.raises(CalculationError, match="未知 CGM 列格式"):
        read_cgm(path, "mmol/L")


def test_early_device_blank_header_template_retains_excel_row_numbers(tmp_path):
    path = tmp_path / "early_synthetic.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, None])
    sheet.append(["2026-01-01 00:00", "5.8"])
    sheet.append(["2026-01-01 00:05", "0"])
    workbook.save(path)
    result = read_cgm(path, "mmol/L")
    assert list(result.source_row) == [2, 3]
    assert list(result.glucose_raw) == ["5.8", "0"]


def test_raw_cleaning_keeps_true_low_and_marks_duplicate_conflict():
    raw = pd.DataFrame(
        {
            "raw_time": [
                "2026-01-01 00:00",
                "2026-01-01 00:01",
                "2026-01-01 00:02",
                "2026-01-01 00:03",
                "2026-01-01 00:03",
                "2026-01-01 00:04",
            ],
            "glucose_raw": ["0", "1.7", "6", "5", "7", "8"],
            "source_row": range(2, 8),
            "source_unit": "mmol/L",
            "device_state": ["", "", "", "", "", "error"],
        }
    )
    evidence, observations, qc = clean_observations(raw)
    assert qc["below_1p8_valid_count"] == 1
    assert qc["zero_count"] == 1
    assert qc["duplicate_conflict_count"] == 1
    assert evidence.loc[1, "glucose_clean"] == 1.7
    assert evidence.loc[3:4, "glucose_clean"].isna().all()
    assert evidence.loc[5, "qc_reason"] == "DEVICE_INVALID"
    assert len(observations) == 5
    assert raw_interval_distribution(evidence)[0] == {
        "interval_seconds": 0.0,
        "adjacent_pairs_n": 1,
    }


@pytest.mark.parametrize("value,state", [("LOW", ""), ("5", "unknown-code")])
def test_unknown_device_reading_stops_file(value, state):
    raw = pd.DataFrame(
        {
            "raw_time": ["2026-01-01 00:00"],
            "glucose_raw": [value],
            "source_row": [2],
            "device_state": [state],
        }
    )
    with pytest.raises(CalculationError) as caught:
        clean_observations(raw)
    assert caught.value.code == "ERROR06"

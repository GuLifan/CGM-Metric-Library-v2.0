import csv
import json

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from cgm_library.contracts.schema import load_config
from cgm_library.io.reader import read_request
from cgm_library.studies.drq import GROUP_FILES, research_windows
from cgm_library.workflows.drq_batch import _excel_parts, run_drq_batch
from cgm_library.workflows.drq_patient import calculate_drq_patient


def inputs(tmp_path, discharge="2026-01-03 08:00:00", stop="2026-01-04 08:00:00"):
    source = tmp_path / "source"
    source.mkdir()
    times = pd.date_range("2026-01-01 08:00", periods=4 * 288, freq="5min")
    values = np.full(len(times), 6.0)
    values[24:27] = 2.8
    pd.DataFrame({"t": times, "v": values}).to_csv(source / "sample.csv", index=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"sources:\n  - path: {source.as_posix()}\n    interval_min: 5\n    unit: mmol/L\n",
        encoding="utf-8",
    )
    request_path = tmp_path / "request.csv"
    with request_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "住院号",
                "出院日期",
                "入院日期",
                "设备文件名",
                "胰岛素泵开始时间",
                "胰岛素泵停止时间",
                "analysis_id",
            ]
        )
        writer.writerow(
            [
                "0001",
                discharge,
                "2025-12-31",
                "sample.csv",
                "2026-01-02 08:00:00",
                stop,
                "SYN001",
            ]
        )
    return request_path, config_path


def test_research_offsets_and_pump_boundaries():
    origin = pd.Timestamp("2026-01-01 08:02", tz="Asia/Shanghai")
    end = origin + pd.Timedelta(days=14)
    windows = research_windows(
        origin, origin, end, origin, origin + pd.Timedelta(days=4), None, None
    )
    assert windows["cgm_d6_11"] == (origin + pd.Timedelta(days=5), origin + pd.Timedelta(days=11))
    assert windows["cgm_day_14"] == (origin + pd.Timedelta(days=13), end)
    assert windows["pump_period"] == (None, None)


def test_long_event_json_survives_excel_cell_limit():
    value = json.dumps(["2026-01-01T10:00:00+08:00"] * 1500)
    frame = _excel_parts(pd.DataFrame({"events_json": [value, None]}))
    assert len(frame.columns) == 2
    assert "".join(frame.iloc[0].tolist()) == value
    assert all(len(part) <= 32000 for part in frame.iloc[0])
    assert frame.iloc[1].isna().all()


def test_missing_pump_stop_does_not_block_other_windows_and_daily_modd(tmp_path):
    request, config = inputs(tmp_path, stop="")
    row = read_request(request).iloc[0].to_dict()
    result = calculate_drq_patient(row, load_config(config)[0])
    assert result["audit"]["pump_period"]["reason"] == "PUMP_STOP_MISSING"
    assert "MEAN" not in result["tables"]["pump_period"]
    assert result["tables"]["cgm_day_2"]["MODD_vs_previous_cgm_day_mmol_L"] > 0
    assert result["tables"]["all_record"]["hypo_episode_lt3p9_n"] == 1
    events = json.loads(result["tables"]["all_record"]["hypo_episode_lt3p9_events_json"])
    assert len(events) == 1 and events[0]["event_type"] == "hypo_episode_lt3p9"
    assert np.isnan(result["tables"]["cgm_day_1"]["MODD_mmol_L"])


def test_batch_exports_exact_approved_files_and_fonts(tmp_path):
    request, config = inputs(tmp_path)
    root = run_drq_batch(request, config, tmp_path, "test", workers=1)
    paths = {f.name for f in (root / "results").iterdir()}
    assert len(paths) == 15 and not any("NEW" in name for name in paths)
    assert any("Mode7_" in name for name in paths) and len(GROUP_FILES) == 13
    pump = pd.read_csv(next((root / "results").glob("*Mode7*csv")), dtype={"住院号": str})
    assert pump.loc[0, "住院号"] == "0001" and pump.loc[0, "MEAN"] == 6
    workbook = load_workbook(next((root / "results").glob("*.xlsx")), read_only=True)
    assert workbook.sheetnames == [f"Day {i}" for i in range(1, 15)]
    assert all(
        cell.font.name == "Times New Roman"
        for row in workbook["Day 1"]
        for cell in row
        if cell.value is not None
    )
    workbook.close()
    assert run_drq_batch(request, config, tmp_path, "test", workers=1, resume=True) == root


def test_first_cgm_after_discharge_still_computes_post_discharge(tmp_path):
    request, config = inputs(tmp_path, discharge="2025-12-31 12:00:00", stop="")
    row = read_request(request).iloc[0].to_dict()
    result = calculate_drq_patient(row, load_config(config)[0])
    assert np.isnan(result["tables"]["pre72h"]["MEAN"])
    assert np.isfinite(result["tables"]["all_record"]["MEAN"])
    assert np.isfinite(result["tables"]["post_record"]["MEAN"])
    assert result["audit"]["pump_period"]["reason"] == "PUMP_STOP_MISSING"

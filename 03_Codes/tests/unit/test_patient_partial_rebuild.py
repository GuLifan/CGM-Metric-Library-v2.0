"""合成五分钟文件从输入读取到两个独立支线，核对 CGM 起点和泵窗口。"""

import pandas as pd

from cgm_library.contracts.schema import RunConfig, SourceFolder
from cgm_library.workflows.patient import calculate_patient_partial


def test_patient_partial_starts_sparse_at_first_valid_raw_reading(tmp_path):
    start = pd.Timestamp("2026-01-01 00:00", tz="Asia/Shanghai")
    times = pd.date_range(start, periods=5 * 288, freq="5min")
    values = [0, *([6.0] * (len(times) - 1))]
    path = tmp_path / "synthetic.csv"
    pd.DataFrame({"t": times.tz_localize(None), "v": values}).to_csv(path, index=False)
    request = {
        "住院号": "TEST0001",
        "出院日期": "2026-01-06 00:00",
        "入院日期": "2026-01-01 00:00",
        "设备文件名": "synthetic.csv",
        "胰岛素泵开始时间": "2026-01-01",
        "胰岛素泵停止时间": "",
        "analysis_id": "SYNTHETIC-001",
        "备注": "对照字段",
    }
    config = RunConfig((SourceFolder(tmp_path, 5, "mmol/L"),))
    result = calculate_patient_partial(request, config)
    assert result.status == "PARTIAL_RULE_GATED"
    assert result.qc["first_raw_time"] == start
    assert result.qc["cgm_start_first_valid_raw_time"] == start + pd.Timedelta(minutes=5)
    assert result.qc["invalid_leading_unique_timestamps_n"] == 1
    assert result.qc["pump_start_precision"] == "DATE_ONLY_NOON"
    assert result.window_rows.loc[
        result.window_rows.window_name.eq("pump_d1"), "window_start"
    ].iloc[0] == (start + pd.Timedelta(hours=12))
    assert result.window_rows.loc[0, "备注"] == "对照字段"
    assert (
        result.window_rows.loc[
            result.window_rows.window_name.eq("inpatient"), "fasting_valid_days_n"
        ].iloc[0]
        >= 2
    )
    assert set(result.window_rows.window_name) == {
        "all_record",
        "inpatient",
        "pre72h",
        "pre24h",
        "pump_d1",
        "pump_d3",
    }
    assert (
        result.window_rows.loc[
            result.window_rows.window_name.eq("inpatient"), "modd_matched_pairs_n"
        ].iloc[0]
        > 0
    )
    assert (
        result.window_rows.loc[
            result.window_rows.window_name.eq("inpatient"), "adrr_valid_days_n"
        ].iloc[0]
        == 5
    )
    assert (
        len(result.daily_risk_rows.loc[result.daily_risk_rows.parent_window.eq("inpatient")]) == 5
    )
    assert not result.day_night_rows.empty
    assert result.day_night_rows.loc[0, "备注"] == "对照字段"
    assert result.night_event_rows.empty
    assert len(result.sparse_targets) == 20
    assert result.sparse5["sparse_d1_valid_n"] == 4
    assert result.sparse5["sparse_pre72h_valid_n"] == 12
    assert result.full7["mean_pre72h"] == 6
    assert result.full7["mean_pump_d1"] == 6
    assert result.full7["delta_mean_pump_d3_d1"] == 0
    assert result.full7["day_p5_pre24h"] == 6
    assert result.full7["night_p5_pre24h"] == 6


def test_all_record_fbs_includes_first_incomplete_sensor_morning(tmp_path):
    times = pd.date_range("2026-01-01 05:55", periods=4, freq="5min")
    pd.DataFrame({"t": times, "v": [4, 5, 7, 8]}).to_csv(tmp_path / "edge.csv", index=False)
    request = {
        "analysis_id": "S",
        "入院日期": "2026-01-01",
        "出院日期": "2026-01-02",
        "设备文件名": "edge.csv",
        "胰岛素泵开始时间": "",
        "胰岛素泵停止时间": "",
    }
    result = calculate_patient_partial(request, RunConfig((SourceFolder(tmp_path, 5, "mmol/L"),)))
    assert set(result.window_rows.window_name) == {"all_record", "inpatient", "pre72h", "pre24h"}
    morning = result.fasting_day_rows.query('window_name == "all_record"').iloc[0]
    assert morning.fasting_valid_points == 4
    assert morning.fasting_cgm_0600 == 6

"""部分批次必须继续其他患者，并明示缺失医学规则导致不能正式发布。"""

import csv
import hashlib
import json

import pandas as pd
import pytest
import yaml

from cgm_library.io.pump_request import PUMP_PREFIX
from cgm_library.workflows.batch import run_partial_batch


def test_partial_batch_writes_audited_assets_without_claiming_formal_success(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    times = pd.date_range("2026-01-01", periods=5 * 288, freq="5min")
    pd.DataFrame({"t": times, "v": 6.0}).to_csv(source / "synthetic.csv", index=False)
    request = tmp_path / "request.csv"
    headers = [
        "住院号",
        "出院日期",
        "入院日期",
        "设备文件名",
        "胰岛素泵开始时间",
        "胰岛素泵停止时间",
        "analysis_id",
        "附加列",
    ]
    with request.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerow(
            ["SYN1", "2026-01-06", "2026-01-01", "synthetic.csv", "2026-01-01", "", "A1", "保留"]
        )
        writer.writerow(
            ["SYN2", "2026-01-06", "2026-01-01", "absent.csv", "2026-01-01", "", "A2", "继续"]
        )
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump({"sources": [{"path": str(source), "interval_min": 5, "unit": "mmol/L"}]}),
        encoding="utf-8",
    )
    output = run_partial_batch(request, config, tmp_path, "synthetic_batch")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PARTIAL_WITH_PATIENT_ERRORS"
    assert manifest["formal_release"] is False
    assert manifest["patient_status_counts"] == {"PARTIAL_RULE_GATED": 1, "ERROR": 1}
    statuses = pd.read_csv(output / "logs/patient_status.csv", dtype=str, keep_default_na=False)
    assert len(statuses) == 2
    assert statuses.loc[1, "error_code"] == "ERROR01"
    metrics = pd.read_csv(output / "metric_outputs/patient_window_metrics.csv", dtype=str)
    assert list(metrics.columns[:6]) == headers[:6]
    assert metrics.loc[0, "附加列"] == "保留"
    assert len(pd.read_csv(output / "metric_outputs/attd_sparse20_targets.csv")) == 20
    assert (
        list(pd.read_csv(output / "metric_outputs/event_level_long_table.csv").columns[:6])
        == headers[:6]
    )
    assert all(
        hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
        for name, digest in manifest["outputs_sha256"].items()
    )
    with pytest.raises(FileExistsError):
        run_partial_batch(request, config, tmp_path, "synthetic_batch")


def test_duplicate_and_overfull_rules_in_batch(tmp_path):
    # 第一病例先有满五点的正常槽，第二槽出现六个不同时间。第三病例
    # 第一槽有六个原始行但仅五个时刻，连续指标和 Sparse 均使用选中的值。
    origin = pd.Timestamp("2026-01-01 06:25")
    regular = list(pd.date_range(origin, periods=5, freq="min"))
    overfull = list(pd.date_range(origin + pd.Timedelta(minutes=5), periods=6, freq="59s"))
    pd.DataFrame({"t": regular + overfull, "v": 5}).to_csv(tmp_path / "over.csv", index=False)
    pd.DataFrame({"t": [origin] * 2, "v": [4, 8]}).to_csv(tmp_path / "conflict.csv", index=False)
    good = pd.date_range(origin + pd.Timedelta(minutes=5), periods=5, freq="min")
    pd.DataFrame({"t": [good[0], *good], "v": ["", "6", 5, 5, 5, 5]}).to_csv(
        tmp_path / "good.csv", index=False
    )
    rows = [
        [stem, "2026-01-02", "2026-01-01", stem + ".csv", "", "", stem]
        for stem in ("over", "conflict", "good")
    ]
    request = tmp_path / "request.csv"
    pd.DataFrame(rows, columns=[*PUMP_PREFIX, "analysis_id"]).to_csv(request, index=False)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump({"sources": [{"path": ".", "interval_min": 1, "unit": "mmol/L"}]}),
        encoding="utf-8",
    )
    output = run_partial_batch(request, config, tmp_path, "duplicate_overfull")
    status = pd.read_csv(output / "logs/patient_status.csv", keep_default_na=False).set_index(
        "analysis_id"
    )
    assert status.error_code.to_dict() == {"over": "ERROR05", "conflict": "ERROR14", "good": ""}
    assert "首个过满槽 1" in status.at["over", "error_message"]
    assert "06:30:00+08:00" in status.at["over", "error_message"]
    assert "[59, 59, 59, 59, 59]" in status.at["over", "error_message"]
    intervals = pd.read_csv(output / "qc_and_coverage/raw_intervals.csv")
    assert (
        intervals.query("analysis_id == 'over' and interval_seconds == 59").adjacent_pairs_n.item()
        == 5
    )
    anomalies = pd.read_csv(output / "qc_and_coverage/raw_anomalies.csv")
    assert anomalies.query("analysis_id == 'conflict'").duplicate_conflict_flag.tolist() == [
        True,
        True,
    ]
    pair = anomalies.query("analysis_id == 'good'").sort_values("source_row")
    assert pair.is_representative.tolist() == [False, True]
    assert pair.raw_qc_reason.tolist() == ["MISSING_INVALID", "OK"]
    metrics = pd.read_csv(output / "metric_outputs/patient_window_metrics.csv")
    assert set(metrics.analysis_id) == {"good"}
    assert metrics.query("window_name == 'all_record'").MEAN.item() == pytest.approx(5.2)
    targets = pd.read_csv(output / "metric_outputs/attd_sparse20_targets.csv")
    match = targets.query("target_id == 'cgm_d1_0630'").iloc[0]
    assert match.glucose == 6 and match.matched_source_row == 3

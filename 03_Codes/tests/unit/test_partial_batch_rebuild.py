"""部分批次必须继续其他患者，并明示缺失医学规则导致不能正式发布。"""

import csv
import hashlib
import json

import pandas as pd
import pytest
import yaml

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

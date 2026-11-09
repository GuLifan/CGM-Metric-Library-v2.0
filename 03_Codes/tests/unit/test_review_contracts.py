"""审查复现：在正常入口覆盖配置、列碰撞及同时间戳的证据。"""

import csv
from datetime import date

import pytest
import yaml

from cgm_library.contracts.schema import CalculationError, load_config
from cgm_library.io.pump_request import PUMP_PREFIX
from cgm_library.io.reader import read_cgm, read_request


@pytest.mark.parametrize("value", ["abc", None, True, float("inf")])
def test_bad_coverage_has_batch_error(tmp_path, value):
    path = tmp_path / "site.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sources": [{"path": "raw", "interval_min": 5, "unit": "mmol/L"}],
                "coverage_pct": value,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CalculationError, match="coverage_pct") as caught:
        load_config(path)
    assert (caught.value.code, caught.value.scope) == ("ERROR03", "batch")


def test_iso_dates_and_touching_source_boundaries(tmp_path):
    import pandas as pd

    sources = [
        {"path": "early", "interval_min": 5, "unit": "mmol/L", "to_date": date(2025, 6, 1)},
        {"path": "late", "interval_min": 1, "unit": "mmol/L", "from_date": "2025-06-01"},
    ]
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    config, _ = load_config(path)
    assert [s.contains(pd.Timestamp("2025-06-01")) for s in config.sources] == [False, True]
    sources[1]["from_date"] = "2025-05-31"
    path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    with pytest.raises(CalculationError, match="重叠"):
        load_config(path)


def test_request_collisions_report_all_names(tmp_path):
    path = tmp_path / "input.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(
            [
                [*PUMP_PREFIX, "analysis_id", "MEAN", "date", "error_code"],
                ["0001", "2026-01-05", "2026-01-01", "x", "", "", "S", "a", "b", "c"],
            ]
        )
    with pytest.raises(CalculationError) as caught:
        read_request(path)
    assert caught.value.scope == "batch"
    assert all(key in str(caught.value) for key in ("MEAN", "date", "error_code"))


def test_normalized_device_columns_must_be_unique(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("T,t,v\n2026-01-01,2026-01-02,5\n", encoding="utf-8")
    with pytest.raises(CalculationError, match="T") as caught:
        read_cgm(path, "mmol/L")
    assert caught.value.code == "ERROR03"


def test_jitter_thresholds_and_clipped_durations():
    import pandas as pd

    from cgm_library.timeline.groups import make_groups
    from cgm_library.workflows.window import calculate_confirmed_window

    start = pd.Timestamp("2026-01-01 12:00", tz="Asia/Shanghai")
    planned = pd.date_range(start, periods=25, freq="5min")
    times = list(planned)
    times[1] += pd.Timedelta(seconds=1)
    groups = make_groups(pd.DataFrame({"timestamp": times, "glucose_clean": [6] + [3.5] * 24}), 5)

    def metrics(minutes):
        return calculate_confirmed_window(
            groups, start, start + pd.Timedelta(minutes=minutes), window_name="test"
        )

    partial, events = metrics(19)
    assert events == []
    assert partial["TIR_minutes"] == 5 and partial["TBR_minutes"] == 14
    assert partial["TBR_pct"] == pytest.approx(100 * 14 / 19)
    assert partial["MEAN"] == (6 + 3 * 3.5) / 4
    _, events = metrics(20)
    assert len(events) == 1 and events[0]["event_start"] == planned[1]
    assert events[0]["first_observed_time"] == times[1]
    assert len(metrics(123)[1]) == 1
    assert len(metrics(125)[1]) == 2
    insufficient, _ = metrics(250)
    assert insufficient["valid_minutes"] == 125
    assert pd.isna(insufficient["TBR_minutes"])


def test_all_failed_schema_and_programming_fault(tmp_path, monkeypatch):
    import json

    import pandas as pd

    from cgm_library.contracts.fields import ASSETS
    from cgm_library.workflows import batch

    headers = [*PUMP_PREFIX, "analysis_id", "附加列"]
    request = tmp_path / "requests.csv"
    pd.DataFrame(
        [["0001", "2026-01-02", "2026-01-01", "missing.csv", "", "", "S", "保留"]], columns=headers
    ).to_csv(request, index=False)
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump({"sources": [{"path": ".", "interval_min": 5, "unit": "mmol/L"}]}),
        encoding="utf-8",
    )
    out = batch.run_partial_batch(request, config, tmp_path, "all_failed")
    assert (
        json.loads((out / "manifest.json").read_text(encoding="utf-8"))["status"]
        == "ALL_PATIENTS_FAILED"
    )
    for key, asset in ASSETS.items():
        table = pd.read_csv(out / asset.path)
        assert list(table.columns) == asset.columns([*headers, "request_row"])
        assert len(table) == int(key == "status")

    def fail(*args):
        raise ValueError("injected internal failure")

    monkeypatch.setattr(batch, "calculate_patient_partial", fail)
    with pytest.raises(ValueError, match="injected"):
        batch.run_partial_batch(request, config, tmp_path, "fault")
    fault = tmp_path / "fault"
    assert json.loads((fault / "run_state.json").read_text(encoding="utf-8"))["status"] == "ABORTED"
    assert "injected internal failure" in (fault / "logs/batch_error.log").read_text(
        encoding="utf-8"
    )
    assert not (fault / "manifest.json").exists()

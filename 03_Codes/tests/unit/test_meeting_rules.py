"""针对已批准医学语义的独立合成案例，不使用真实患者资料。"""

import json

import numpy as np
import pandas as pd
import pytest

from cgm_library.contracts.schema import CalculationError, RunConfig, SourceFolder
from cgm_library.events.engine import confirmed_event_types
from cgm_library.io.reader import locate_source
from cgm_library.metrics.daily import adrr_by_day
from cgm_library.timeline.groups import make_groups
from cgm_library.workflows.patient import calculate_patient_partial
from cgm_library.workflows.window import calculate_confirmed_window


def groups(values, start="2026-01-01 00:00"):
    times = pd.date_range(start, periods=len(values), freq="5min", tz="Asia/Shanghai")
    return make_groups(
        pd.DataFrame(
            {"timestamp": times, "glucose_clean": values, "source_row": range(len(values))}
        ),
        5,
    )


@pytest.mark.parametrize(
    "low,kind", [(3.5, "extended_hypo_lt3p9_120"), (2.5, "prolonged_level2_lt3p0_120")]
)
def test_one_parent_two_continuous_runs(low, kind):
    g = groups([6] * 3 + [low] * 24 + [6] + [low] * 24 + [6] * 3)
    events = confirmed_event_types(g, g.group_start.iloc[0], g.group_end.iloc[-1])
    extended = [e for e in events if e["event_type"] == kind]
    assert len(extended) == 1
    children = json.loads(extended[0]["continuous_low_segments_json"])
    assert [c["duration_min"] for c in children] == [120, 120]
    assert (
        pd.Timestamp(children[1]["start"]) - pd.Timestamp(children[0]["end"])
    ).total_seconds() == 300


def test_normal_fifteen_minutes_separates_extended_parents():
    g = groups([6] * 3 + [3.5] * 24 + [6] * 3 + [3.5] * 24 + [6] * 3)
    events = confirmed_event_types(g, g.group_start.iloc[0], g.group_end.iloc[-1])
    assert sum(e["event_type"] == "extended_hypo_lt3p9_120" for e in events) == 2


def test_condition_strict_threshold_counts_and_missing():
    g = groups([6] * 3 + [3.0] * 3 + [6] * 3 + [3.4] * 3 + [6] * 3)
    row, _ = calculate_confirmed_window(
        g, g.group_start.iloc[0], g.group_end.iloc[-1], window_name="test"
    )
    assert row["hypo_cond_lt3p0_n"] == 0
    assert row["hypo_cond_lt3p5_n"] == 2
    assert row["hypo_cond_lt3p5_any"] == 1
    row, _ = calculate_confirmed_window(
        g, g.group_start.iloc[0], g.group_end.iloc[-1] + pd.Timedelta(days=2), window_name="test"
    )
    assert np.isnan(row["hypo_cond_lt3p5_n"])


def test_adrr_partial_and_complete_days_are_distinct():
    g = groups([12] * 108 + [6] * 288, start="2026-01-01 15:00")
    row, days = adrr_by_day(g, g.group_start.iloc[0], g.group_end.iloc[-1])
    assert [d["is_partial_day"] for d in days] == [True, False]
    assert days[0]["expected_points"] == 108
    assert row["adrr_complete_valid_days_n"] == 1
    assert row["ADRR_complete_days"] == pytest.approx(days[1]["adrr_daily_sum"])
    assert row["ADRR"] == pytest.approx(np.mean([d["adrr_daily_sum"] for d in days]))


@pytest.mark.parametrize("stop", ["2026-01-01 10:00", "2026-01-01 12:00"])
def test_bad_pump_order_preserves_other_results(tmp_path, stop):
    times = pd.date_range("2026-01-01", periods=5 * 288, freq="5min")
    pd.DataFrame({"t": times, "v": 6}).to_csv(tmp_path / "synthetic.csv", index=False)
    request = {
        "住院号": "SYN",
        "出院日期": "2026-01-06",
        "入院日期": "2026-01-01",
        "设备文件名": "synthetic.csv",
        "胰岛素泵开始时间": "2026-01-01",
        "胰岛素泵停止时间": stop,
        "analysis_id": "SYN",
    }
    result = calculate_patient_partial(request, RunConfig((SourceFolder(tmp_path, 5, "mmol/L"),)))
    assert np.isnan(result.full7["mean_pump_d1"])
    assert result.full7["mean_pre72h"] == 6
    assert result.full7["pump_d1d3_reason"] == "PUMP_STOP_NOT_AFTER_START"
    assert result.sparse5["sparse_mean_pre72h"] == 6
    assert not result.window_rows.window_name.str.startswith("pump").any()


def test_cleaned_input_is_never_fallback(tmp_path):
    source = tmp_path / "source_cleaned"
    source.mkdir()
    with pytest.raises(CalculationError, match="cleaned"):
        locate_source(
            {"出院日期": "2026-01-01", "设备文件名": "a.csv"},
            RunConfig((SourceFolder(source, 5, "mmol/L"),)),
        )

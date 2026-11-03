"""01.md 明示公式的合成手算例，覆盖单位、缺失与时间配对。"""

import numpy as np
import pandas as pd

from cgm_library.metrics.core import gri_from_percentages, modd, pooled_metrics
from cgm_library.metrics.fasting import fasting_cv, fasting_values


def test_gri_uses_percent_not_proportion_and_caps_at_100():
    manual = gri_from_percentages(tbr2_pct=25, tbr1_pct=25, tar2_pct=25, tar1_pct=0)
    assert manual["hypoglycemia_component"] == 135
    assert manual["hyperglycemia_component"] == 40
    assert manual["GRI_raw"] == 175
    assert manual["GRI"] == 100
    from_readings = pooled_metrics([2.5, 3.5, 8.0, 14.0])
    assert from_readings["TBR2_pct"] == from_readings["TBR1_pct"] == 25
    assert from_readings["TAR2_pct"] == 25
    assert from_readings["TIR_minutes"] == 5
    assert (
        from_readings["TBR_minutes"] + from_readings["TIR_minutes"] + from_readings["TAR_minutes"]
        == from_readings["valid_minutes"]
    )
    assert from_readings["GRI"] == 100


def test_sample_sd_and_valid_positive_below_1p8_remain_visible():
    result = pooled_metrics([1.6, 7.0])
    assert result["MEAN"] == 4.3
    assert np.isclose(result["SD"], np.std([1.6, 7.0], ddof=1))
    assert result["min_value_qc_flag"] == "BELOW_1P8_VALID"
    assert result["global_min"] == 1.6
    assert result["CV_pct"] > 0


def test_modd_never_pairs_day1_to_day3():
    times = pd.DatetimeIndex(["2026-01-01 06:00", "2026-01-03 06:00"], tz="Asia/Shanghai")
    frame = pd.DataFrame({"group_start": times, "glucose_clean": [6.0, 8.0]})
    assert modd(frame)["modd_matched_pairs_n"] == 0
    frame.loc[len(frame)] = [pd.Timestamp("2026-01-02 06:00", tz="Asia/Shanghai"), 7.0]
    result = modd(frame)
    assert result["modd_matched_pairs_n"] == 2
    assert result["MODD_mmol_L"] == 1.0


def test_fasting_requires_four_of_six_and_ignores_postdischarge_morning():
    start = pd.Timestamp("2026-01-01", tz="Asia/Shanghai")
    times = pd.date_range(start, periods=3 * 288, freq="5min")
    values = np.full(len(times), 6.0)
    first = 69  # 05:45 在每天的第 69 个五分钟槽
    values[first : first + 2] = np.nan
    values[288 + first : 288 + first + 2] = np.nan
    values[2 * 288 + first : 2 * 288 + 6] = 20.0
    groups = pd.DataFrame({"group_start": times, "glucose_clean": values})
    rows = fasting_values(
        groups, start, start + pd.Timedelta(days=3), start, start + pd.Timedelta(days=2)
    )
    assert len(rows) == 2
    assert [row["fasting_valid_points"] for row in rows] == [4, 4]
    result = fasting_cv(rows)
    assert result["fasting_valid_days_n"] == 2
    assert result["fasting_cgm_0600_cv_pct"] == 0
    values[288 + first + 2] = np.nan
    groups["glucose_clean"] = values
    rows = fasting_values(
        groups, start, start + pd.Timedelta(days=3), start, start + pd.Timedelta(days=2)
    )
    assert rows[1]["fasting_reason"] == "FBS_LT4_OF6"
    assert fasting_cv(rows)["fasting_cv_reason"] == "LT2_VALID_DAYS"

"""Sparse20 取点的原始血糖血缘及五项完整性边界。"""

import numpy as np
import pandas as pd
import pytest

from cgm_library.sampling.fixed_clock import extract_sparse20
from cgm_library.studies.attd.sparse import sparse_features


def test_twenty_raw_targets_and_five_features():
    cgm_start = pd.Timestamp("2026-01-01 08:00", tz="Asia/Shanghai")
    discharge = cgm_start + pd.Timedelta(days=5)
    times = pd.date_range(cgm_start, discharge - pd.Timedelta(minutes=1), freq="min")
    raw = pd.DataFrame(
        {"timestamp": times, "glucose_clean": 6.0, "source_row": range(2, len(times) + 2)}
    )
    targets, candidates = extract_sparse20(raw, cgm_start, discharge)
    assert len(targets) == 20
    assert targets.target_id.nunique() == 20
    assert targets.glucose.notna().sum() == 20
    assert len(candidates) > 20  # 保存全部 ±10 分钟候选，而非只保存被选点
    assert candidates.is_nearest.sum() == 20
    targets.loc[targets.window_name.eq("cgm_d3"), "glucose"] = 4.0
    features = sparse_features(targets)
    assert features["sparse_mean_cgm_d1"] == 6
    assert features["sparse_delta_mean_cgm_d3_d1"] == -2
    assert features["sparse_mean_pre72h"] == 6
    assert features["sparse_min_pre72h"] == 6
    assert features["sparse_cv_pre72h_pct"] == 0
    first_pre_index = targets.loc[targets.window_name.eq("pre72h_d1")].index[0]
    targets.loc[first_pre_index, "glucose"] = np.nan
    incomplete = sparse_features(targets)
    assert np.isnan(incomplete["sparse_mean_pre72h"])
    assert np.isnan(incomplete["sparse_min_pre72h"])
    assert np.isnan(incomplete["sparse_cv_pre72h_pct"])


def test_tied_nearest_stays_na_and_all_candidates_are_retained():
    start = pd.Timestamp("2026-01-01", tz="Asia/Shanghai")
    discharge = start + pd.Timedelta(days=5)
    raw = pd.DataFrame(
        {
            "timestamp": [
                start,
                start + pd.Timedelta(hours=6, minutes=25),
                start + pd.Timedelta(hours=6, minutes=35),
            ],
            "glucose_clean": [6.0, 4.0, 8.0],
            "source_row": [2, 3, 4],
        }
    )
    targets, candidates = extract_sparse20(raw, start, discharge)
    target = targets.loc[targets.window_name.eq("cgm_d1") & targets.clock.eq("06:30")].iloc[0]
    assert target.reason == "TIED_NEAREST" and pd.isna(target.glucose)
    related = candidates.loc[candidates.target_id.eq(target.target_id)]
    assert len(related) == 2 and related.is_nearest.all()


def test_aggregated_grid_cannot_enter_sparse_branch():
    start = pd.Timestamp("2026-01-01", tz="Asia/Shanghai")
    aggregate = pd.DataFrame({"timestamp": [start], "group_start": [start], "glucose_clean": [6.0]})
    with pytest.raises(ValueError, match="原始观测"):
        extract_sparse20(aggregate, start, start + pd.Timedelta(days=5))

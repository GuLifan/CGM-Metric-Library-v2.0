"""只由 Sparse20 的离散原始点派生五项；完整性为 4/8/12。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sparse_features(targets: pd.DataFrame) -> dict[str, float | int | str]:
    """完整目标必须恰好 20 个；五项不从连续血糖指标倒推。"""
    if len(targets) != 20 or targets.target_id.duplicated().any():
        raise ValueError("Sparse5 必须由 20 个唯一原始取点目标派生")
    counts = targets.window_name.value_counts()
    expected = {"cgm_d1": 4, "cgm_d3": 4, **{f"pre72h_d{i}": 4 for i in range(1, 4)}}
    if counts.to_dict() != expected:
        raise ValueError("Sparse20 的 D1/D3/出院前三日目标分配不完整")
    d1 = targets.loc[targets.window_name.eq("cgm_d1"), "glucose"].to_numpy(float)
    d3 = targets.loc[targets.window_name.eq("cgm_d3"), "glucose"].to_numpy(float)
    pre = targets.loc[targets.window_name.str.startswith("pre72h_d"), "glucose"].to_numpy(float)
    n1, n3, npre = (int(np.isfinite(values).sum()) for values in (d1, d3, pre))
    complete_d1 = n1 == 4
    complete_d1d3 = n1 + n3 == 8
    complete_pre = npre == 12
    return {
        "sparse_mean_cgm_d1": float(d1.mean()) if complete_d1 else np.nan,
        "sparse_delta_mean_cgm_d3_d1": (float(d3.mean() - d1.mean()) if complete_d1d3 else np.nan),
        "sparse_mean_pre72h": float(pre.mean()) if complete_pre else np.nan,
        "sparse_min_pre72h": float(pre.min()) if complete_pre else np.nan,
        "sparse_cv_pre72h_pct": (
            float(pre.std(ddof=1) / pre.mean() * 100) if complete_pre else np.nan
        ),
        "sparse_d1_valid_n": n1,
        "sparse_d3_valid_n": n3,
        "sparse_pre72h_valid_n": npre,
        "sparse_mean_cgm_d1_reason": "" if complete_d1 else "D1_LT4",
        "sparse_delta_mean_cgm_d3_d1_reason": "" if complete_d1d3 else "D1D3_LT8",
        "sparse_pre72h_reason": "" if complete_pre else "PRE72H_LT12",
        "sparse_protocol": "attd_sparse20_v2_20261010",
    }

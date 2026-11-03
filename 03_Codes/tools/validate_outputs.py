"""独立核对批次资产；不依据生成器的SUCCESS标签直接相信结果。"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def validate(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["outputs_sha256"].items():
        path = (root / name).resolve()
        if root.resolve() not in path.parents:
            raise ValueError("清单包含越界路径")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"资产校验失败: {name}")
    statuses = pd.read_csv(root / "logs/patient_status.csv")
    if len(statuses) != manifest["patient_count"]:
        raise ValueError("患者状态行数与清单不一致")
    counts = statuses.patient_status.value_counts().to_dict()
    if counts != manifest["patient_status_counts"]:
        raise ValueError("患者状态计数与清单不一致")
    if manifest["formal_release"] and manifest.get("pending_rule_gates"):
        raise ValueError("仍有未验收项却声称正式发布")
    metrics = pd.read_csv(root / "metric_outputs/patient_window_metrics.csv")
    if not metrics.empty:
        if (metrics.valid_points > metrics.expected_points).any():
            raise ValueError("有效点超过理论点")
        valid = metrics[["TIR_minutes", "TAR_minutes", "TBR_minutes", "valid_minutes"]].dropna()
        if not np.allclose(
            valid.TIR_minutes + valid.TAR_minutes + valid.TBR_minutes, valid.valid_minutes
        ):
            raise ValueError("TIR/TAR/TBR分钟分区不一致")
    sparse = pd.read_csv(root / "metric_outputs/attd_sparse20_targets.csv")
    if not sparse.empty and not sparse.groupby("analysis_id").size().eq(20).all():
        raise ValueError("Sparse20目标数不等于20")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    validate(args.output)
    print("Output integrity checks passed.")

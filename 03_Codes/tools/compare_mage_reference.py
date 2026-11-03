"""冻结合成曲线，运行官方R参考并报告差异；不自动调参或签署通过。"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from cgm_library.metrics.mage import calculate_mage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rscript", type=Path, required=True)
    parser.add_argument("--r-library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    t = np.arange(576)
    cases = {
        "smooth": 6 + 3 * np.sin(t / 12),
        "flat": np.full(576, 6.0),
        "different_segment_variability": np.r_[
            6 + np.sin(np.arange(240) / 12),
            np.full(96, np.nan),
            8 + 4 * np.sin(np.arange(240) / 12),
        ],
    }
    rows, candidate = [], {}
    times = pd.date_range("2026-01-01", periods=576, freq="5min", tz="Asia/Shanghai")
    for name, values in cases.items():
        candidate[name] = calculate_mage(times, values)["value"]
        rows.extend(
            {"id": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "gl": value * 18}
            for time, value in zip(times, values)
        )
    input_path = args.output / "input.csv"
    pd.DataFrame(rows).to_csv(input_path, index=False)
    reference_script = Path(__file__).with_name("reference_mage.R")
    result = subprocess.run(
        [
            str(args.rscript),
            str(reference_script),
            str(args.r_library),
            str(input_path),
            str(args.output / "reference.csv"),
            str(args.output / "session.txt"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    (args.output / "console.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise SystemExit("R参考执行失败；详见console.txt，不能标记验证通过")
    reference = pd.read_csv(args.output / "reference.csv").set_index("id")
    comparisons = []
    for name, value in candidate.items():
        ref = float(reference.loc[name, "reference_mmol_L"])
        comparisons.append(
            {
                "case": name,
                "python_candidate": float(value) if np.isfinite(value) else None,
                "r_reference": ref if np.isfinite(ref) else None,
                "absolute_difference": abs(float(value) - ref)
                if np.isfinite(value) and np.isfinite(ref)
                else None,
                "missingness_equal": bool(np.isfinite(value) == np.isfinite(ref)),
            }
        )
    from cgm_library.metrics import mage

    report = {
        "status": "COMPARISON_ONLY_REQUIRES_REVIEW",
        "formal_accepted": False,
        "policy": "Whole-window SD; do not tune parameters to match segment-SD reference",
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "implementation_sha256": hashlib.sha256(Path(mage.__file__).read_bytes()).hexdigest(),
        "reference_script_sha256": hashlib.sha256(reference_script.read_bytes()).hexdigest(),
        "comparisons": comparisons,
    }
    (args.output / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

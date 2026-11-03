"""脱敏试运行：时间轴、边界夜窗、已确认指标/事件与 Sparse20→Sparse5。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from cgm_library.sampling.fixed_clock import extract_sparse20
from cgm_library.studies.attd.sparse import sparse_features
from cgm_library.timeline.groups import make_groups
from cgm_library.windows.coverage import window_view
from cgm_library.windows.definitions import night_intersections
from cgm_library.workflows.window import calculate_confirmed_window


def _raw(times, values):
    return pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(times, tz="Asia/Shanghai"),
            "glucose_clean": values,
            "source_row": range(2, len(times) + 2),
        }
    )


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_pilot(output_root: Path, run_id: str) -> Path:
    """仅生成合成数据资产；已存在 run_id 时拒绝覆盖。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("run_id 只能包含字母、数字、下划线和短横线")
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    qc_dir = output / "qc_and_coverage"
    metrics_dir = output / "metric_outputs"
    log_dir = output / "logs"
    for path in (qc_dir, metrics_dir, log_dir):
        path.mkdir()
    # 反例：两个组的首有效原始时刻都落在日历 12:55 槽，组首仍相隔 5 分钟。
    collision_raw = _raw(
        [
            "2026-01-01 12:51:40",
            "2026-01-01 12:52:40",
            "2026-01-01 12:53:40",
            "2026-01-01 12:54:40",
            "2026-01-01 12:55:40",
            "2026-01-01 12:56:40",
            "2026-01-01 12:58:54",
        ],
        [np.nan, np.nan, np.nan, np.nan, 6.4, np.nan, 6.8],
    )
    minute_groups = make_groups(collision_raw, 1)
    minute_groups.to_csv(qc_dir / "minute_groups.csv", index=False, encoding="utf-8-sig")
    slot_start = pd.Timestamp("2026-01-01 12:50", tz="Asia/Shanghai")
    _, minute_qc = window_view(minute_groups, slot_start, slot_start + pd.Timedelta(minutes=10))
    if (minute_qc["expected_points"], minute_qc["valid_points"]) != (2, 2):
        raise AssertionError("分钟来源归槽回归案例未通过")
    five_raw = _raw(["2026-01-01 08:00:31", "2026-01-01 08:04:51"], [6.1, 6.4])
    five_groups = make_groups(five_raw, 5)
    five_groups.to_csv(qc_dir / "five_min_collision_groups.csv", index=False, encoding="utf-8-sig")
    if not five_groups.slot_conflict_flag.iloc[0] or pd.notna(five_groups.glucose_clean.iloc[0]):
        raise AssertionError("原始五分钟同槽多值未置 NA")
    night_start = pd.Timestamp("2026-01-02 03:00", tz="Asia/Shanghai")
    night_end = pd.Timestamp("2026-01-02 06:00", tz="Asia/Shanghai")
    night = night_intersections(night_start, night_end)
    # 在局部三小时夜窗造连续三槽 Level2；保留充分覆盖，用于验证 15 分钟事件。
    night_values = [6.0] * 36
    night_values[6:9] = [2.8] * 3
    night_raw = _raw(pd.date_range(night_start, periods=36, freq="5min"), night_values)
    night_groups = make_groups(night_raw, 5)
    _, night_qc = window_view(night_groups, night[0][0], night[0][1])
    night_metrics, night_events = calculate_confirmed_window(
        night_groups, night[0][0], night[0][1], window_name="truncated_night_03to06"
    )
    if (
        night_metrics["valid_minutes"] != 180
        or night_metrics["TBR_minutes"] != 15
        or {event["event_type"] for event in night_events}
        != {"hypo_episode_lt3p9", "level2_period_lt3p0"}
    ):
        raise AssertionError("已确认的夜间连续指标与 15 分钟事件案例未通过")
    pd.DataFrame([{"synthetic_case": "truncated_night_level2", **night_metrics}]).to_csv(
        metrics_dir / "confirmed_night_metrics.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(night_events).to_csv(
        metrics_dir / "confirmed_night_events.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(
        [
            {"synthetic_case": "minute_source_group_start", **minute_qc},
            {"synthetic_case": "truncated_night_03to06", **night_qc},
        ]
    ).to_csv(qc_dir / "coverage.csv", index=False, encoding="utf-8-sig")
    # 独立原始支线：五天逐分钟合成值产生 20 个固定时点原始候选。
    cgm_start = pd.Timestamp("2026-01-01 08:00", tz="Asia/Shanghai")
    discharge = cgm_start + pd.Timedelta(days=5)
    times = pd.date_range(cgm_start, discharge - pd.Timedelta(minutes=1), freq="min")
    sparse_raw = _raw(times, [6.0] * len(times))
    targets, candidates = extract_sparse20(sparse_raw, cgm_start, discharge)
    sparse5 = sparse_features(targets)
    if len(targets) != 20 or targets.glucose.notna().sum() != 20:
        raise AssertionError("Sparse20 完整性案例未通过")
    targets.to_csv(qc_dir / "sparse20_targets.csv", index=False, encoding="utf-8-sig")
    candidates.to_csv(qc_dir / "sparse20_candidates.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"synthetic_case": "constant_raw_glucose", **sparse5}]).to_csv(
        metrics_dir / "sparse5.csv", index=False, encoding="utf-8-sig"
    )
    config = {
        "synthetic_only": True,
        "timezone": "Asia/Shanghai",
        "coverage_min_pct": 70,
        "sparse_clock_times": ["06:30", "11:00", "17:30", "22:00"],
        "sparse_tolerance_min": 10,
        "confirmed_synthetic_metrics_run": True,
        "full_formal_metrics_run": False,
    }
    (output / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    environment = {
        "python": platform.python_version(),
        "pandas": version("pandas"),
        "numpy": version("numpy"),
        "library": version("cgm-metric-library"),
    }
    (output / "environment.yaml").write_text(
        yaml.safe_dump(environment, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (log_dir / "pilot.log").write_text(
        "SYNTHETIC_PARTIAL: timeline, coverage, confirmed core metrics/events and Sparse5.\n"
        "Synthetic inputs only; MAGE candidates are not formal validated results.\n",
        encoding="utf-8",
    )
    manifest = {
        "run_id": run_id,
        "status": "SYNTHETIC_PARTIAL",
        "synthetic_only": True,
        "patient_count": 0,
        "validated_cases": [
            "minute_source_group_start",
            "five_minute_collision_na",
            "truncated_night_03to06",
            "confirmed_night_metrics_and_15min_events",
            "sparse20_raw_to_sparse5",
        ],
        "pending_gates": ["mage_reference_validation", "formal_patient_batch"],
        "outputs_sha256": {
            str(path.relative_to(output)): _hash(path)
            for path in output.rglob("*")
            if path.is_file()
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run de-identified CGM timeline and Sparse pilot")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--output-root", type=Path, default=Path(__file__).resolve().parents[2] / "_Outputs"
    )
    args = parser.parse_args()
    print(run_pilot(args.output_root, args.run_id))


if __name__ == "__main__":
    main()

"""显式运行受控部分批次；甲方完整指标未齐时不可宣称正式交付。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cgm_library.workflows.batch import run_partial_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a traceable, non-formal partial CGM batch")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--output-root", type=Path, default=Path(__file__).resolve().parents[2] / "_Outputs"
    )
    parser.add_argument(
        "--accept-partial",
        action="store_true",
        help="Acknowledge that MAGE reference acceptance is still pending",
    )
    args = parser.parse_args()
    if not args.accept_partial:
        parser.error("必须明确传入 --accept-partial，输出不得称为甲方完整结果")
    output = run_partial_batch(args.request, args.config, args.output_root, args.run_id)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "status": manifest["status"],
                "patient_count": manifest["patient_count"],
                "patient_status_counts": manifest["patient_status_counts"],
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

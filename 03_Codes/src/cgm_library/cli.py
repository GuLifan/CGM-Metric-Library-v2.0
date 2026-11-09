"""公开批次入口；医学参数由SPEC固定，数据位置由本地配置提供。"""

import argparse
import json
import sys
from pathlib import Path

from cgm_library.contracts.schema import CalculationError
from cgm_library.workflows.batch import run_partial_batch


def main() -> int:
    """未完成参考验收时要求明确承认研究性输出状态。"""
    parser = argparse.ArgumentParser(description="CGM Metric Library v2.0.0")
    parser.add_argument("--version", action="version", version="2.0.0")
    commands = parser.add_subparsers(dest="command", required=True)
    batch = commands.add_parser("run", help="计算批次，保存QC、结果与日志")
    batch.add_argument("--request", type=Path, required=True)
    batch.add_argument("--config", type=Path, required=True)
    batch.add_argument("--output-root", type=Path, required=True)
    batch.add_argument("--run-id", required=True)
    batch.add_argument(
        "--accept-partial", action="store_true", help="接受MAGE参考未验收的研究性输出"
    )
    args = parser.parse_args()
    if not args.accept_partial:
        parser.error("MAGE参考验收未完成；试运行需 --accept-partial")
    try:
        output = run_partial_batch(args.request, args.config, args.output_root, args.run_id)
    except CalculationError as exc:
        print(
            json.dumps(
                {"code": exc.code, "scope": exc.scope, "message": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    except FileExistsError as exc:
        print(f"运行目录已存在，请使用新的 run_id：{exc}", file=sys.stderr)
        return 2
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({"output": str(output), "status": manifest["status"]}, ensure_ascii=False))

    return 1 if manifest["status"] == "ALL_PATIENTS_FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())

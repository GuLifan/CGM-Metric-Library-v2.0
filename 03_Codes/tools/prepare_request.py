"""把旧请求表与患者表做一次可追溯匹配，生成新的前六列泵时间请求表。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cgm_library.io.pump_request import augment_request, read_csv_strings, write_csv_new


def sha256(path: Path) -> str:
    """输入输出都固定散列，支持以后复核文件是否被手工改过。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_resolution(path: Path) -> dict[str, int]:
    """人工行号只放受控本地 JSON；源码和 Git 均不包含患者标识。"""
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or not content:
        raise ValueError("人工行号文件必须是非空的住院号到原 CSV 行号映射")
    if not all(isinstance(key, str) and type(value) is int for key, value in content.items()):
        raise ValueError("人工行号映射必须使用字符串住院号和整数原 CSV 行号")
    return content


def prepare(
    request_path: Path,
    patient_path: Path,
    resolution_path: Path,
    output_path: Path,
    qc_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    """先在内存中完成全部匹配和行数校验，随后只创建新文件。"""
    destinations = (output_path, qc_path, manifest_path)
    if len(set(destinations)) != 3 or any(path.exists() for path in destinations):
        raise FileExistsError("输出路径重复或已存在；禁止覆盖已有请求表、QC 或 manifest")
    for destination in destinations:
        if not destination.parent.is_dir():
            raise FileNotFoundError(f"输出目录不存在：{destination.parent}")
    request_headers, request_rows = read_csv_strings(request_path)
    patient_headers, patient_rows = read_csv_strings(patient_path)
    resolution = read_resolution(resolution_path)
    headers, rows, qc = augment_request(
        request_headers, request_rows, patient_headers, patient_rows, resolution
    )
    if len(rows) != len(request_rows) or len(qc) != len(request_rows):
        raise RuntimeError("输出或 QC 行数与原请求表不一致")
    qc_headers = list(qc[0])
    write_csv_new(output_path, headers, rows)
    write_csv_new(qc_path, qc_headers, qc)
    summary: dict[str, object] = {
        "created_at_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "status": "REQUEST_PREPARED_NOT_METRIC_RESULT",
        "request_rows": len(rows),
        "first_six_headers": headers[:6],
        "match_mode_counts": dict(Counter(item["match_mode"] for item in qc)),
        "pump_end_missing_n": sum(bool(item["pump_end_missing"]) for item in qc),
        "pump_end_not_after_start_n": sum(bool(item["pump_end_not_after_start"]) for item in qc),
        "sha256": {
            "original_request": sha256(request_path),
            "patient_source": sha256(patient_path),
            "manual_resolution": sha256(resolution_path),
            "prepared_request": sha256(output_path),
            "request_qc": sha256(qc_path),
        },
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the approved six-column CGM request")
    for name in ("request", "patients", "resolution", "output", "qc", "manifest"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    summary = prepare(
        args.request, args.patients, args.resolution, args.output, args.qc, args.manifest
    )
    # 终端只报告汇总数；具体患者标识留在 Git 排除的请求表和 QC。
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "sha256"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()

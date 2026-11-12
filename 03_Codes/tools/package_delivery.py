"""Package readable deliverables and verify every archived byte against the run manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "COMPLETED_RESEARCH" or manifest.get("delivery_revision") != "261112":
        raise ValueError("A completed revised delivery is required")
    prefix = output.stem
    temporary = output.with_suffix(".zip.tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    expected = {}
    try:
        with ZipFile(temporary, "x", compression=ZIP_DEFLATED, compresslevel=6) as target:
            for name in manifest["delivery_files"]:
                path = (root / "results" / name).resolve()
                if path.parent != root / "results":
                    raise ValueError("Unsafe delivery path")
                with path.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                if digest != manifest["outputs_sha256"]["results/" + name]:
                    raise ValueError(f"Changed delivery asset: {name}")
                entry = prefix + "/" + name
                target.write(path, entry)
                expected[entry] = digest
        with ZipFile(temporary) as target:
            assert set(target.namelist()) == set(expected)
            for name, digest in expected.items():
                with target.open(name) as handle:
                    assert hashlib.file_digest(handle, "sha256").hexdigest() == digest, name
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    with output.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    output.with_suffix(".zip.sha256").write_text(
        digest + "  " + output.name + "\n", encoding="utf-8"
    )
    return {
        "archive": str(output),
        "files": len(expected),
        "bytes": output.stat().st_size,
        "sha256": digest,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.run, args.archive), ensure_ascii=False))

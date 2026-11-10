"""Collapse and restore a verified result ZIP as one patient CSV, preserving every asset byte."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import zipfile
import zlib
from pathlib import Path


def _pack(data):
    return base64.b64encode(zlib.compress(data, 6)).decode("ascii")


def _unpack(text):
    return zlib.decompress(base64.b64decode(text, validate=True))


def _flush(database, owner, name, spec, block):
    if block:
        database.execute(
            "insert into fragments values (?,?,?,?)",
            (owner, name, spec["blocks"], _pack(bytes(block))),
        )
        spec["blocks"] += 1
        block.clear()


class _Lines:
    def __init__(self, handle):
        self.handle = handle
        self.parts = []

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self.handle)
        self.parts.append(line)
        return line

    def take(self):
        value = "".join(self.parts).encode("utf-8")
        self.parts.clear()
        return value


def _safe(root, name):
    path = (root / name).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("Archive path escapes the destination")
    return path


def collapse_results(archive: Path, flat_results: Path, output: Path):
    """Keep readable scalar results and reversible per-patient compressed CSV fragments."""
    if output.exists():
        raise FileExistsError(output)
    with flat_results.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames)
        patients = list(reader)
    ids = [row["analysis_id"] for row in patients]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate patient key")
    identity = set(ids)
    metadata = {"version": 1, "codec": "base64(zlib(utf8-json))", "assets": {}}
    temp = output.with_suffix(".csv.tmp")
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="collapse_") as scratch:
        database = sqlite3.connect(Path(scratch) / "fragments.sqlite")
        database.execute("create table fragments (id text, path text, seq integer, data text)")
        database.execute("create index patient_fragments on fragments(id)")
        with zipfile.ZipFile(archive) as source:
            for asset in source.infolist():
                if asset.is_dir():
                    continue
                name = asset.filename
                digest = hashlib.sha256()
                spec = {"sha256": "", "bytes": asset.file_size, "blocks": 0}
                metadata["assets"][name] = spec
                if name.endswith(".csv"):
                    with source.open(asset) as stream:
                        lines = _Lines(io.TextIOWrapper(stream, encoding="utf-8", newline=""))
                        reader = csv.reader(lines)
                        header = next(reader)
                        raw_header = lines.take()
                        digest.update(raw_header)
                        spec["header"] = base64.b64encode(raw_header).decode("ascii")
                        headers = [v.lstrip("\ufeff") for v in header]
                        index = headers.index("analysis_id") if "analysis_id" in headers else None
                        timeline_id = None
                        if "timeline_groups/request_" in name:
                            ordinal = int(Path(name).stem.removeprefix("request_")) - 1
                            timeline_id = ids[ordinal]
                        owner = None
                        block = bytearray()

                        for row in reader:
                            raw = lines.take()
                            digest.update(raw)
                            patient = row[index] if index is not None else timeline_id
                            if patient is None:
                                patient = ids[0]
                            if patient not in identity:
                                raise ValueError(f"Unknown patient in {name}")
                            if patient != owner or len(block) > 1024 * 1024:
                                _flush(database, owner, name, spec, block)
                            owner = patient
                            block.extend(raw)
                        _flush(database, owner, name, spec, block)
                else:
                    with source.open(asset) as stream:
                        data = stream.read()
                    digest.update(data)
                    spec["binary"] = _pack(data)
                spec["sha256"] = digest.hexdigest()
            manifest = json.loads(source.read("manifest.json"))
            for path, expected in manifest["outputs_sha256"].items():
                if metadata["assets"][path]["sha256"] != expected:
                    raise ValueError(f"Manifest hash mismatch in {path}")
            expected = source.read("manifest.sha256").decode("ascii").split()[0]
            if metadata["assets"]["manifest.json"]["sha256"] != expected:
                raise ValueError("Manifest checksum mismatch")
        database.commit()
        with temp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns
                + ["calculation_details_zlib_base64", "archive_metadata_zlib_base64"],
                lineterminator="\n",
            )
            writer.writeheader()
            for i, patient in enumerate(patients):
                fragments = [
                    {"path": path, "sequence": seq, "data": data}
                    for path, seq, data in database.execute(
                        "select path,seq,data from fragments where id=? order by path,seq",
                        (patient["analysis_id"],),
                    )
                ]
                patient["calculation_details_zlib_base64"] = _pack(
                    json.dumps(fragments, separators=(",", ":")).encode()
                )
                patient["archive_metadata_zlib_base64"] = (
                    _pack(json.dumps(metadata, separators=(",", ":")).encode()) if i == 0 else ""
                )
                writer.writerow(patient)
        database.close()
    temp.replace(output)
    return output


def restore_results(table: Path, output: Path):
    """Restore all original asset bytes and verify their hashes before publishing the directory."""
    if output.exists():
        raise FileExistsError(output)
    csv.field_size_limit(2**31 - 1)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="restore_") as scratch:
        root = Path(scratch)
        stage = root / "assets"
        stage.mkdir()
        database = sqlite3.connect(root / "fragments.sqlite")
        database.execute(
            "create table fragments (path text, seq integer, data text, primary key(path,seq))"
        )
        metadata = None
        with table.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["archive_metadata_zlib_base64"]:
                    if metadata is not None:
                        raise ValueError("Repeated archive metadata")
                    metadata = json.loads(_unpack(row["archive_metadata_zlib_base64"]))
                for item in json.loads(_unpack(row["calculation_details_zlib_base64"])):
                    database.execute(
                        "insert into fragments values (?,?,?)",
                        (item["path"], item["sequence"], item["data"]),
                    )
        if metadata is None or metadata["version"] != 1:
            raise ValueError("Missing or unsupported archive metadata")
        if {v[0] for v in database.execute("select distinct path from fragments")} - set(
            metadata["assets"]
        ):
            raise ValueError("Unregistered fragments")
        for name, spec in metadata["assets"].items():
            file = _safe(stage, name)
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("wb") as stream:
                if "binary" in spec:
                    stream.write(_unpack(spec["binary"]))
                else:
                    stream.write(base64.b64decode(spec["header"], validate=True))
                    sequences = 0
                    for seq, data in database.execute(
                        "select seq,data from fragments where path=? order by seq", (name,)
                    ):
                        if seq != sequences:
                            raise ValueError("Missing fragment sequence")
                        stream.write(_unpack(data))
                        sequences += 1
                    if sequences != spec["blocks"]:
                        raise ValueError("Missing asset fragments")
            with file.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if file.stat().st_size != spec["bytes"] or digest != spec["sha256"]:
                raise ValueError(f"Restored hash mismatch in {name}")
        database.close()
        stage.rename(output)
    return output

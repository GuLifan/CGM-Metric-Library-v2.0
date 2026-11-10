import csv
import hashlib
import json
import zipfile

from cgm_library.io.archive import collapse_results, restore_results


def test_single_csv_restores_multiline_records_and_binary_bytes(tmp_path):
    assets = {
        "provenance/request.csv": b"analysis_id,name\r\nP1,001\r\nP2,002\r\n",
        "metric_outputs/events.csv": (
            b'analysis_id,event\r\nP1,"line one\nline two"\r\nP2,zero\r\nP1,last\r\n'
        ),
        "qc_and_coverage/timeline_groups/request_0002.csv": b"time,value\nnow,1.2345\n",
        "empty.csv": b"analysis_id,value\n",
        "result.xlsx": bytes(range(256)),
    }
    manifest = {"outputs_sha256": {k: hashlib.sha256(v).hexdigest() for k, v in assets.items()}}
    assets["manifest.json"] = json.dumps(manifest).encode()
    assets["manifest.sha256"] = hashlib.sha256(assets["manifest.json"]).hexdigest().encode()
    archive = tmp_path / "details.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in assets.items():
            bundle.writestr(name, data)
    flat = tmp_path / "results.csv"
    flat.write_text("analysis_id,MEAN\nP1,1.2345\nP2,0.0000\n", encoding="utf-8-sig")
    table = tmp_path / "single.csv"
    collapse_results(archive, flat, table)
    with table.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [r["MEAN"] for r in rows] == ["1.2345", "0.0000"]
    restored = tmp_path / "restored"
    restore_results(table, restored)
    assert {
        p.relative_to(restored).as_posix(): p.read_bytes()
        for p in restored.rglob("*")
        if p.is_file()
    } == assets

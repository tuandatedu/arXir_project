"""Export a complete, version-aware M1 report from Colab Drive checkpoints.

Run from repo root:
 python -m src.m1_crawling.export_reports --backup-dir /content/drive/MyDrive/arxiv-m1/range_5

The source archives are never unpacked; only their JSONL/metrics entries are read.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import tarfile
from typing import Any

PAPER_FIELDS = ["arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue"]
RECORD_FIELDS = ["arxiv_id", "status", "versions", "error", "elapsed_sec", "batch"]
FAILED_FIELDS = ["arxiv_id", "version", "versioned_id", "status", "reason", "batch"]


def _read_jsonl(tf: tarfile.TarFile, name: str) -> list[dict]:
    try:
        entry = tf.extractfile(name)
    except KeyError as exc:
        raise ValueError(f"Archive missing required file: {name}") from exc
    if entry is None:
        raise ValueError(f"Archive missing required file: {name}")
    with entry:
        return [json.loads(line) for line in entry if line.strip()]


def _json_value(value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _json_value(row.get(key)) for key in fields})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_reports(backup_dir: Path, report_dir: Path | None = None,
                   verify_sha256: bool = False) -> dict:
    backup_dir = Path(backup_dir)
    report_dir = Path(report_dir) if report_dir else backup_dir / "reports"
    if not backup_dir.is_dir():
        raise FileNotFoundError(f"Backup directory does not exist: {backup_dir}")
    archives = sorted(backup_dir.glob("batch_*.tar.gz"))
    if not archives:
        raise FileNotFoundError(f"No batch_*.tar.gz found in {backup_dir}")

    papers: list[dict] = []
    records: list[dict] = []
    metrics: list[dict] = []
    failed: list[dict] = []
    batches: list[dict] = []
    seen_ids: set[str] = set()
    for archive in archives:
        name = archive.name.removesuffix(".tar.gz")
        marker = backup_dir / (name + ".json")
        if not marker.exists():
            raise ValueError(f"Missing completion marker: {marker}")
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        if manifest.get("archive_bytes") != archive.stat().st_size:
            raise ValueError(f"Checkpoint size mismatch: {archive.name}")
        if verify_sha256 and manifest.get("archive_sha256") != _sha256(archive):
            raise ValueError(f"Checkpoint SHA256 mismatch: {archive.name}")
        with tarfile.open(archive, "r:gz") as tf:
            paper_rows = _read_jsonl(tf, "papers.jsonl")
            record_rows = _read_jsonl(tf, "crawl_records.jsonl")
            try:
                metrics_file = tf.extractfile("metrics.json")
                batch_metrics = json.load(metrics_file) if metrics_file else {}
            except KeyError:
                batch_metrics = {}
        expected = set(manifest.get("ids", []))
        actual = {str(row.get("arxiv_id")) for row in record_rows}
        if len(record_rows) != len(actual) or actual != expected:
            raise ValueError(f"Record IDs do not match manifest: {archive.name}")
        if seen_ids & actual:
            raise ValueError(f"Overlapping IDs between batches: {archive.name}")
        seen_ids.update(actual)
        for row in paper_rows:
            papers.append(row)
        for row in record_rows:
            row = {**row, "batch": name}
            records.append(row)
            if row.get("status") == "error":
                bad_versions = [v for v in (row.get("versions") or [])
                                if v.get("status") == "error"]
                if not bad_versions:
                    failed.append({"arxiv_id": row["arxiv_id"], "version": "",
                                   "versioned_id": "", "status": "error",
                                   "reason": row.get("error") or "unknown",
                                   "batch": name})
                for v in bad_versions:
                    ver = v.get("version")
                    failed.append({"arxiv_id": row["arxiv_id"], "version": ver,
                                   "versioned_id": f"{row['arxiv_id']}v{ver}",
                                   "status": "error", "reason": v.get("reason") or "unknown",
                                   "batch": name})
        metrics.append({**batch_metrics, "batch": name})
        batches.append({"batch": name, "requested": len(record_rows),
                        "ok": sum(r.get("status") == "ok" for r in record_rows),
                        "error": sum(r.get("status") == "error" for r in record_rows)})

    counts = {key: sum(r.get("status") == key for r in records)
              for key in ("ok", "error", "no_tex", "not_found")}
    summary = {
        "batch_count": len(batches),
        "total_records": len(records),
        "metadata_rows": len(papers),
        "ok": counts["ok"],
        "error": counts["error"],
        "no_tex": counts["no_tex"],
        "not_found": counts["not_found"],
        "failed_version_rows": len(failed),
        "latest_checkpoint_http_requests": sum(int(m.get("api_requests_this_run") or 0) for m in metrics),
        "latest_checkpoint_retries": sum(int(m.get("api_retries_this_run") or 0) for m in metrics),
        "latest_checkpoint_runtime_seconds": round(sum(float(m.get("runtime_seconds_this_run") or 0) for m in metrics), 3),
        "metrics_note": "Metrics describe the last execution of each batch, NOT cumulative fast+recovery time.",
        "batches": batches,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(report_dir / "papers.csv", papers, PAPER_FIELDS)
    _write_csv(report_dir / "crawl_records.csv", records, RECORD_FIELDS)
    metric_fields = sorted({key for row in metrics for key in row})
    _write_csv(report_dir / "metrics.csv", metrics, metric_fields)
    _write_csv(report_dir / "failed_versions.csv", failed, FAILED_FIELDS)
    (report_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--verify-sha256", action="store_true")
    args = parser.parse_args()
    summary = export_reports(args.backup_dir, args.report_dir, args.verify_sha256)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

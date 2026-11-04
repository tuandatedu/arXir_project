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

from src.m1_crawling.runtime_tracking import (
    HISTORY_FIELDS, read_runtime_history, summarize_runtime,
)

PAPER_FIELDS = ["arxiv_id", "title", "authors", "submission_date", "revised_dates", "venue"]
RECORD_FIELDS = ["arxiv_id", "status", "versions", "error", "elapsed_sec", "batch"]
FAILED_FIELDS = ["arxiv_id", "version", "versioned_id", "status", "reason", "batch"]
ISSUE_FIELDS = ["arxiv_id", "versioned_id", "batch", "status", "category",
                "explanation_vi", "suggestion_vi", "retry_suggested", "technical_reason"]


def _explain_issue(status: str, reason: str) -> tuple[str, str, str, str]:
    """Classify a source issue without erasing its original technical reason."""
    detail = (reason or "").lower()
    if status == "no_tex":
        if "source_pdf" in detail:
            return ("PDF_ONLY", "arXiv chỉ trả về PDF, không có source LaTeX.",
                    "Ghi nhận no_tex; không retry như lỗi mạng.", "no")
        if "source_http_404" in detail or "source_http_410" in detail:
            return ("SOURCE_UNAVAILABLE", "Không có source tải về ở endpoint này.",
                    "Ghi nhận no_tex; kiểm tra thủ công nếu cần.", "no")
        return ("NO_TEX", "Archive không chứa file .tex/.bib dùng được.",
                "Ghi nhận no_tex; không retry liên tục.", "no")
    if status == "not_found":
        return ("NOT_FOUND", "Không tìm thấy metadata bài báo ở lần tra cứu.",
                "Kiểm tra ID và tra cứu lại sau nếu nghi API lỗi.", "check")
    if "429" in detail:
        return ("RATE_LIMIT", "arXiv giới hạn số yêu cầu (HTTP 429).",
                "Tạm dừng, chờ lâu hơn rồi Recovery; không tăng tốc hoặc chạy song song.", "later")
    if "incompleteread" in detail or "chunkedencodingerror" in detail:
        return ("INCOMPLETE_DOWNLOAD", "Kết nối bị ngắt trước khi tải xong source.",
                "Recovery lại phiên bản này sau khi mạng ổn định.", "yes")
    if "timeout" in detail or "timed out" in detail:
        return ("TIMEOUT", "Yêu cầu tải dữ liệu hết thời gian chờ.",
                "Recovery sau; kiểm tra kết nối nếu lặp lại.", "yes")
    if "http 5" in detail or "503" in detail or "502" in detail:
        return ("SERVER_ERROR", "Máy chủ tạm thời không đáp ứng yêu cầu.",
                "Chờ rồi Recovery; không gửi yêu cầu dồn dập.", "later")
    if detail.startswith("discovery:"):
        return ("DISCOVERY_ERROR", "Không lấy được metadata trong lần tra cứu.",
                "Kiểm tra lỗi API, thử lại sau.", "later")
    return ("OTHER_ERROR", "Lỗi kỹ thuật khác, cần xem chi tiết.",
            "Đọc technical_reason trước khi quyết định retry.", "check")


def _issues_for_record(record: dict, batch: str) -> list[dict]:
    status = record.get("status", "")
    if status == "ok":
        return []
    versions = [v for v in (record.get("versions") or [])
                if isinstance(v, dict) and v.get("status") in ("error", "no_tex")]
    if not versions:
        versions = [{"version": None, "status": status,
                     "reason": record.get("error") or "unknown"}]
    issues = []
    for version in versions:
        st = version.get("status") or status
        reason = str(version.get("reason") or record.get("error") or "")
        category, explanation, suggestion, retry = _explain_issue(st, reason)
        ver = version.get("version")
        paper_id = str(record["arxiv_id"])
        issues.append({"arxiv_id": paper_id,
                       "versioned_id": f"{paper_id}v{ver}" if ver is not None else paper_id,
                       "batch": batch, "status": st, "category": category,
                       "explanation_vi": explanation, "suggestion_vi": suggestion,
                       "retry_suggested": retry, "technical_reason": reason})
    return issues



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
    issues: list[dict] = []
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
            issues.extend(_issues_for_record(row, name))
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
    issue_counts: dict[str, int] = {}
    for issue in issues:
        category = issue["category"]
        issue_counts[category] = issue_counts.get(category, 0) + 1
    snapshot = backup_dir / "_before_recovery"
    snapshot_bytes = sum(f.stat().st_size for f in snapshot.rglob("*") if f.is_file()) if snapshot.is_dir() else 0
    checkpoint_bytes = sum(a.stat().st_size for a in archives)
    # The wall-clock ledger is the cumulative source of truth. Checkpoint metrics
    # describe only the latest run of each batch and must NOT be summed as history.
    runtime_rows = read_runtime_history(backup_dir)
    runtime_summary = summarize_runtime(runtime_rows, len(records))
    summary = {
        **runtime_summary,
        "issue_counts": issue_counts,
        "issue_rows": len(issues),
        "checkpoint_archive_bytes": checkpoint_bytes,
        "recovery_snapshot_bytes": snapshot_bytes,
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
    _write_csv(report_dir / "issues_explained_vi.csv", issues, ISSUE_FIELDS)
    _write_csv(report_dir / "runtime_history.csv", runtime_rows, HISTORY_FIELDS)
    report_text = [
        "BÁO CÁO CRAWL ARXIV — DỄ ĐỌC",
        f"Số batch: {len(batches)} | Số ID: {len(records)}",
        f"Thành công: {counts['ok']} | Lỗi tải: {counts['error']} | Không có TeX: {counts['no_tex']} | Không tìm thấy: {counts['not_found']}",
        "",
        "PHÂN LOẠI VẤN ĐỀ (theo phiên bản):",
    ]
    report_text.extend(f"- {name}: {count}" for name, count in sorted(issue_counts.items()))
    report_text += [
        "", "ĐỌC FILE NÀO?",
        "- issues_explained_vi.csv: mỗi phiên bản có vấn đề, nguyên nhân dễ hiểu, có nên retry hay không.",
        "- failed_versions.csv: lỗi kỹ thuật nguyên bản, chỉ gồm các phiên bản lỗi.",
        "- crawl_records.csv: kết quả theo bài báo; versions là JSON chứa chi tiết từng phiên bản.",
        "- papers.csv: metadata; không phải bằng chứng rằng LaTeX đã tải thành công.",
        "- metrics.csv: chỉ số lần chạy CUỐI của mỗi batch, không phải tổng thời gian crawl.",
        "- runtime_history.csv: từng lần chạy Cell 4/6 được đo bằng đồng hồ thực tế.",
        "", "THỜI GIAN (chỉ gồm các lần đã được ghi vào runtime_history.csv):",
        f"- Fast Crawl: {runtime_summary['fast_crawl_seconds']:.1f} giây ({runtime_summary['fast_crawl_runs']} lần)",
        f"- Recovery: {runtime_summary['recovery_seconds']:.1f} giây ({runtime_summary['recovery_attempts']} lần)",
        f"- Tổng: {runtime_summary['total_runtime_seconds']:.1f} giây",
        f"- Trung bình trên ID đã xử lý: {runtime_summary['average_seconds_per_id']} giây/ID",
        "- Các lần chạy trước khi cài bản vá không được tự động khôi phục.",
        "- Chạy Export nhiều lần không cộng trùng thời gian.",
        "", "DUNG LƯỢNG:",
        f"- Checkpoint hiện tại: {checkpoint_bytes / 1024**2:.2f} MiB",
        f"- Bản sao _before_recovery: {snapshot_bytes / 1024**2:.2f} MiB",
        "- _before_recovery chỉ là bản sao cũ; không phải dữ liệu mới cần cho report.",
        "- Chỉ xóa bản sao nếu đã kiểm tra checkpoint hiện tại và không cần khôi phục lịch sử.",
        "", "LƯU Ý: 'error' có thể chỉ là 1 phiên bản thất bại, không nhất thiết mọi phiên bản của bài đều lỗi.",
    ]
    (report_dir / "README_BAO_CAO.txt").write_text("\n".join(report_text) + "\n", encoding="utf-8")
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

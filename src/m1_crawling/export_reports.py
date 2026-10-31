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


def _read_phase_metrics(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _summarize_phase_metrics(rows: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for phase in ("semantic_scholar", "tables_build", "tables_validate"):
        phase_rows = [row for row in rows if row.get("phase") == phase]
        durations = [float(row.get("elapsed_seconds") or 0) for row in phase_rows]
        successful = [row for row in phase_rows if row.get("status") == "ok"]
        samples = sum(int(row.get("rss_samples") or 0) for row in successful)
        rss_sum = sum(int(row.get("average_rss_bytes") or 0)
                      * int(row.get("rss_samples") or 0) for row in successful)
        cpu_samples = sum(int(row.get("cpu_samples") or 0) for row in successful)
        cpu_sum = sum(float(row.get("average_cpu_percent") or 0)
                      * int(row.get("cpu_samples") or 0) for row in successful)
        summary[phase] = {
            "runs": len(phase_rows),
            "successful_runs": len(successful),
            "error_runs": len(phase_rows) - len(successful),
            "total_elapsed_seconds": round(sum(durations), 3),
            "average_elapsed_seconds": round(sum(durations) / len(durations), 3)
            if durations else 0,
            "average_process_cpu_percent": round(cpu_sum / cpu_samples, 2)
            if cpu_samples else 0,
            "peak_process_cpu_percent": round(max(
                (float(row.get("peak_cpu_percent") or 0) for row in successful),
                default=0), 2),
            "cpu_samples": cpu_samples,
            "peak_process_rss_bytes": max(
                (int(row.get("peak_rss_bytes") or 0) for row in successful), default=0
            ),
            "average_process_rss_bytes": round(rss_sum / samples) if samples else 0,
            "rss_samples": samples,
        }
    return summary


def _output_size_report(data_dir: Path) -> tuple[int, dict[str, int]]:
    groups = {name: 0 for name in ("checkpoints", "references", "tables", "other")}
    for path in Path(data_dir).rglob("*"):
        try:
            if not path.is_file() or path.name.endswith(".partial"):
                continue
            relative = path.relative_to(data_dir)
            parts = relative.parts
            if "tables" in parts:
                group = "tables"
            elif any(part.startswith("reference_") for part in parts):
                group = "references"
            elif path.name.startswith("batch_") or path.name == "runtime_history.csv":
                group = "checkpoints"
            else:
                group = "other"
            groups[group] += path.stat().st_size
        except OSError:
            continue
    return sum(groups.values()), groups


def _performance_summary(runtime_rows: list[dict], metric_rows: list[dict],
                         total_papers: int) -> dict:
    def seconds(rows: list[dict]) -> float:
        return sum(float(row.get("elapsed_seconds") or 0) for row in rows)

    arxiv_events = [row for row in metric_rows if row.get("phase") == "arxiv_crawl"]
    s2_events = [row for row in metric_rows if row.get("phase") == "semantic_scholar"]
    table_events = [row for row in metric_rows if row.get("phase") == "tables_build"]
    validate_events = [row for row in metric_rows if row.get("phase") == "tables_validate"]
    arxiv_wall = (sum(float(row["elapsed_seconds"]) for row in runtime_rows)
                  if runtime_rows else seconds(arxiv_events))
    phase_wall = seconds(s2_events + table_events + validate_events)
    end_to_end = arxiv_wall + phase_wall
    arxiv_papers = sum(int(row.get("papers_processed") or 0) for row in arxiv_events)
    s2_papers = sum(int(row.get("papers_processed") or 0) for row in s2_events)
    samples = [row for row in metric_rows if int(row.get("rss_samples") or 0) > 0]
    rss_samples = sum(int(row.get("rss_samples") or 0) for row in samples)
    rss_weighted = sum(int(row.get("average_rss_bytes") or 0)
                       * int(row.get("rss_samples") or 0) for row in samples)
    cpu_samples = [row for row in metric_rows if int(row.get("cpu_samples") or 0) > 0]
    cpu_count = sum(int(row.get("cpu_samples") or 0) for row in cpu_samples)
    cpu_weighted = sum(float(row.get("average_cpu_percent") or 0)
                       * int(row.get("cpu_samples") or 0) for row in cpu_samples)
    persistent_peaks = [int(row.get("persistent_output_bytes") or 0)
                        for row in metric_rows]
    scratch_peaks = [int(row.get("sampled_peak_scratch_bytes") or 0)
                     for row in metric_rows]
    estimated_disk = max((out + scratch for out, scratch in
                          zip(persistent_peaks, scratch_peaks)), default=0)
    return {
        "arxiv_wall_seconds": round(arxiv_wall, 3),
        "arxiv_wall_source": "runtime_history.csv" if runtime_rows
        else "performance_metrics.csv batch events (command overhead unavailable)",
        "semantic_scholar_wall_seconds": round(seconds(s2_events), 3),
        "table_build_wall_seconds": round(seconds(table_events), 3),
        "table_validation_wall_seconds": round(seconds(validate_events), 3),
        "end_to_end_wall_seconds": round(end_to_end, 3),
        "end_to_end_seconds_per_unique_paper": round(end_to_end / total_papers, 3)
        if total_papers else None,
        "arxiv_seconds_per_processed_paper": round(seconds(arxiv_events) / arxiv_papers, 3)
        if arxiv_papers else None,
        "semantic_scholar_seconds_per_api_attempt": round(seconds(s2_events) / s2_papers, 3)
        if s2_papers else None,
        "arxiv_papers_processed_including_retries": arxiv_papers,
        "semantic_scholar_api_attempts_including_retries": s2_papers,
        "discovery_seconds_including_retries": round(sum(
            float(row.get("discovery_seconds") or 0) for row in arxiv_events
        ), 3),
        "peak_process_tree_rss_bytes": max(
            (int(row.get("peak_rss_bytes") or 0) for row in samples), default=0
        ),
        "average_process_tree_rss_bytes": round(rss_weighted / rss_samples)
        if rss_samples else 0,
        "average_process_tree_cpu_percent": round(cpu_weighted / cpu_count, 2)
        if cpu_count else 0,
        "peak_process_tree_cpu_percent": round(max(
            (float(row.get("peak_cpu_percent") or 0) for row in cpu_samples), default=0
        ), 2),
        "sampled_peak_scratch_bytes": max(scratch_peaks, default=0),
        "peak_persistent_output_bytes": max(persistent_peaks, default=0),
        "estimated_peak_disk_bytes": estimated_disk,
        "measurement_note": (
            "End-to-end is the sum of sequential arXiv command wall times and recorded "
            "S2/build/validation phase wall times. RSS/CPU are sampled process-tree values. "
            "Disk peak estimates persistent output plus sampled scratch; final output bytes "
            "are measured separately."
        ),
    }


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
    phase_file = backup_dir / "reports" / "performance_metrics.csv"
    phase_rows = _read_phase_metrics(phase_file)
    # Retain historical measurements recorded under earlier filenames.
    for legacy_name in ("metric_CPU.csv", "phase_metrics.csv"):
        legacy_rows = _read_phase_metrics(backup_dir / "reports" / legacy_name)
        known_run_ids = {row.get("run_id") for row in phase_rows}
        phase_rows.extend(row for row in legacy_rows
                          if row.get("run_id") not in known_run_ids)
    phase_summary = _summarize_phase_metrics(phase_rows)
    performance = _performance_summary(runtime_rows, phase_rows, len(records))
    summary = {
        **runtime_summary,
        "phase_metrics": phase_summary,
        "performance": performance,
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
    if phase_rows:
        _write_csv(report_dir / "performance_metrics.csv", phase_rows,
                   list(phase_rows[0].keys()))
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
    report_text += [
        "", "PERFORMANCE SUMMARY (seconds / bytes):",
        f"- End-to-end wall time: {performance['end_to_end_wall_seconds']}",
        f"- End-to-end seconds per unique paper: {performance['end_to_end_seconds_per_unique_paper']}",
        f"- Discovery, including retries: {performance['discovery_seconds_including_retries']}",
        f"- Peak / average process-tree RSS: {performance['peak_process_tree_rss_bytes']} / {performance['average_process_tree_rss_bytes']}",
        f"- Estimated peak disk (persistent + scratch): {performance['estimated_peak_disk_bytes']}",
        "- Detailed rows: performance_metrics.csv; arXiv command wall times: runtime_history.csv.",
    ]
    (report_dir / "README_BAO_CAO.txt").write_text("\n".join(report_text) + "\n", encoding="utf-8")
    summary_path = report_dir / "summary.json"
    for _ in range(2):
        (final_bytes, output_breakdown) = _output_size_report(backup_dir)
        summary["performance"]["final_output_bytes"] = final_bytes
        summary["performance"]["final_output_breakdown_bytes"] = output_breakdown
        summary_path.write_text(
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

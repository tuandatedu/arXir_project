
"""
Công cụ gán nhãn thủ công và tổng hợp kết quả M3.

- BibTeX: đọc bibtex.json hoặc bibtex.jsonl (kể cả bên trong M2 ZIP).
- References: đọc references.json (mảng JSON) hoặc references.jsonl.
- Manual templates: lưu tại data/labels/manual/{arxiv_id}.csv.
- Manual labels: lưu tại data/labels/manual/{arxiv_id}.json.

QUY TẮC MANUAL LABELING:
- Chỉ lấy BibTeX entry có trường bib_title gốc và không rỗng.
- Không sử dụng title được suy luận từ authors để thay thế bib_title.
- Entry không có bib_title sẽ không được xuất vào manual template.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import zipfile

from pathlib import Path
from typing import Any

from src.common.config import DATA_DIR
from src.common.io import read_json, read_jsonl, write_json

from src.m3_matching.cleaning import (
    prepare_bibtex_record,
    prepare_reference_record,
)

from src.m3_matching.features import (
    author_overlap,
    title_similarity,
    year_distance,
)

from src.m3_matching.labelling import (
    load_labels,
    validate_label_quota,
)


# ============================================================
# 1. ĐỌC DỮ LIỆU
# ============================================================

def load_json_records(path: Path) -> list[dict[str, Any]]:
    """Đọc JSON hoặc JSONL thành danh sách records."""

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path)

    if path.suffix.lower() != ".json":
        raise ValueError(f"Định dạng không hỗ trợ: {path.suffix}")

    content = path.read_text(encoding="utf-8-sig").strip()

    if not content:
        return []

    try:
        data = json.loads(content)

    except json.JSONDecodeError:
        # Hỗ trợ JSONL nhưng mang đuôi .json
        records = []

        for line_no, line in enumerate(content.splitlines(), start=1):
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))

            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSON lỗi tại dòng {line_no} trong {path}"
                ) from exc

        return records

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "records", "items"):
            if isinstance(data.get(key), list):
                return data[key]

        return [data]

    raise ValueError(f"Cấu trúc JSON không hợp lệ: {path}")


def load_bibtex_records(path: Path) -> list[dict[str, Any]]:
    """
    Đọc BibTeX từ:
    - .json chứa mảng records.
    - .jsonl trực tiếp.
    - .zip chứa bibtex.json hoặc bibtex.jsonl.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy BibTeX: {path}")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as archive:

            members = [
                name
                for name in archive.namelist()
                if Path(name).name.lower()
                in ("bibtex.json", "bibtex.jsonl")
            ]

            if not members:
                raise FileNotFoundError(
                    f"Không tìm thấy bibtex.json/bibtex.jsonl "
                    f"bên trong {path.name}"
                )

            members.sort(
                key=lambda name:
                Path(name).name.lower() != "bibtex.json"
            )

            if (
                len(members) > 1
                and Path(members[0]).name.lower()
                == Path(members[1]).name.lower()
            ):
                raise ValueError(
                    "ZIP chứa nhiều file BibTeX cùng tên:\n"
                    + "\n".join(members)
                    + "\nHãy chỉ rõ file cần đọc."
                )

            with archive.open(members[0], "r") as file:
                text = io.TextIOWrapper(
                    file,
                    encoding="utf-8-sig",
                ).read()

        if text.lstrip().startswith("["):
            return json.loads(text)

        return [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]

    return load_json_records(path)


def load_reference_records(path: Path) -> list[dict[str, Any]]:
    """Đọc References từ JSON hoặc JSONL."""

    return load_json_records(path)


# ============================================================
# 2. KIỂM TRA BIB_TITLE
# ============================================================

def has_bib_title(bib: dict[str, Any]) -> bool:
    """
    Kiểm tra BibTeX entry có bib_title gốc hay không.

    Không fallback sang title, title_norm hoặc title được
    suy luận từ authors.
    """

    title = bib.get("bib_title")

    return (
        title is not None
        and bool(str(title).strip())
    )


# ============================================================
# 3. TÌM PUBLICATION ĐỦ ĐIỀU KIỆN MANUAL
# ============================================================

def find_candidate_manual_papers(
    bibtex_path: Path,
    references_path: Path,
    min_entries: int = 20,
    min_references: int = 20,
    coverage_ratio: float = 0.1,
) -> list[tuple[str, int, int]]:
    """
    Tìm publications đủ điều kiện cho manual labeling.

    Tiêu chí:
    - Có ít nhất min_entries BibTeX entries có bib_title.
    - Có ít nhất min_references References.
    - Coverage ratio >= coverage_ratio.

    Lưu ý:
    Chỉ đếm BibTeX entry có bib_title.
    """

    bib_records = load_bibtex_records(bibtex_path)
    ref_records = load_reference_records(references_path)

    # Đếm BibTeX có bib_title
    bib_counts: dict[str, int] = {}

    for record in bib_records:
        pid = record.get("arxiv_id")

        if pid and has_bib_title(record):
            bib_counts[pid] = bib_counts.get(pid, 0) + 1

    # Đếm References có arXiv ID
    ref_counts: dict[str, int] = {}

    for record in ref_records:
        pid = record.get("arxiv_id")
        ref_id = (
            record.get("ref_arxiv_id_norm")
            or record.get("ref_arxiv_id")
        )

        if pid and ref_id:
            ref_counts[pid] = ref_counts.get(pid, 0) + 1

    eligible = []

    for pid, bib_count in bib_counts.items():
        ref_count = ref_counts.get(pid, 0)

        if bib_count < min_entries:
            continue

        if ref_count < min_references:
            continue

        actual_ratio = (
            ref_count / bib_count
            if bib_count > 0
            else 0.0
        )

        if actual_ratio >= coverage_ratio:
            eligible.append((pid, bib_count, ref_count))

    # Ưu tiên publications có nhiều references và BibTeX
    eligible.sort(
        key=lambda item: (
            -item[2],
            -item[1],
            -(item[2] / item[1]),
        )
    )

    return eligible


# ============================================================
# 4. XUẤT MANUAL TEMPLATE
# ============================================================

def _bibtex_id(
    bib: dict[str, Any],
    arxiv_id: str,
) -> str:
    """Lấy ID của BibTeX entry."""

    for field in (
        "bibtex_id",
        "bib_id",
        "entry_id",
        "id",
    ):
        value = bib.get(field)

        if value not in (None, ""):
            return str(value)

    return f"{arxiv_id}:{bib.get('citation_key') or ''}"


def _ref_id(ref: dict[str, Any]) -> str:
    """Lấy arXiv ID của reference."""

    return str(
        ref.get("ref_arxiv_id_norm")
        or ref.get("ref_arxiv_id")
        or ""
    )


def _ref_title(ref: dict[str, Any]) -> str:
    """Lấy title của reference."""

    return str(
        ref.get("ref_title")
        or ref.get("title")
        or ""
    )


def export_manual_template(
    arxiv_id: str,
    output_csv: Path,
    bibtex_path: Path,
    references_path: Path,
    use_doi_resolver: bool = True,
) -> Path:
    """
    Xuất template CSV cho manual labeling.

    Chỉ xuất BibTeX entry có bib_title gốc và không rỗng.

    Thứ tự tìm candidate:
    1. DOI của BibTeX trùng DOI của reference -> score 1.00.
    2. DOI resolver tìm được arXiv ID nằm trong references -> 0.90.
    3. Title + author + year similarity -> score >= 0.50.

    Entry không có bib_title sẽ bị loại trước khi xử lý.
    """

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_bib = load_bibtex_records(bibtex_path)
    all_refs = load_reference_records(references_path)

    # --------------------------------------------------------
    # Chỉ lấy BibTeX entry:
    # - Thuộc publication đang xét.
    # - Có bib_title trong dữ liệu gốc.
    # --------------------------------------------------------

    paper_bib = [
        prepare_bibtex_record(record)
        for record in all_bib
        if (
            record.get("arxiv_id") == arxiv_id
            and has_bib_title(record)
        )
    ]

    paper_refs = [
        prepare_reference_record(record)
        for record in all_refs
        if record.get("arxiv_id") == arxiv_id
    ]

    if not paper_bib:
        raise ValueError(
            f"Không tìm thấy BibTeX entry có bib_title "
            f"của {arxiv_id}"
        )

    if not paper_refs:
        raise ValueError(
            f"Không tìm thấy References của {arxiv_id}"
        )

    # Chỉ xét reference có arXiv ID
    candidate_refs = [
        ref
        for ref in paper_refs
        if _ref_id(ref)
    ]

    refs_by_id = {
        _ref_id(ref): ref
        for ref in candidate_refs
    }

    # --------------------------------------------------------
    # Xây dựng DOI -> arXiv ID map
    # --------------------------------------------------------

    doi_map: dict[str, str] = {}

    if use_doi_resolver:
        from src.m3_matching.doi_resolver import (
            build_doi_to_arxiv_map,
        )

        doi_map = build_doi_to_arxiv_map(all_bib)

    # --------------------------------------------------------
    # CSV columns
    # --------------------------------------------------------

    fieldnames = [
        "bibtex_id",
        "citation_key",
        "bib_title",
        "bib_authors",
        "bib_year",
        "bib_doi",
        "bib_raw",
        "suggested_ref_arxiv_id",
        "suggested_ref_title",
        "suggested_score",
        "groundtruth_arxiv_id",
        "is_verified",
        "note",
    ]

    exported_count = 0

    with output_csv.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()

        for bib in paper_bib:

            # Đã lọc bib_title từ dữ liệu gốc ở paper_bib.
            # Không cần kiểm tra hoặc fallback title tại đây.

            best_ref: dict[str, Any] | None = None
            best_score = 0.0

            bib_doi = bib.get("doi_norm")

            # ------------------------------------------------
            # 1. DOI trùng trực tiếp
            # ------------------------------------------------

            if bib_doi:
                for ref in candidate_refs:

                    ref_doi = ref.get("doi_norm")

                    if ref_doi and ref_doi == bib_doi:
                        best_ref = ref
                        best_score = 1.0
                        break

            # ------------------------------------------------
            # 2. DOI -> arXiv ID -> reference
            # ------------------------------------------------

            if (
                best_ref is None
                and bib_doi
                and doi_map
            ):
                from src.m3_matching.doi_resolver import (
                    resolve_arxiv_by_doi,
                )

                resolved = resolve_arxiv_by_doi(
                    bib_doi,
                    doi_map,
                )

                if resolved and resolved in refs_by_id:
                    best_ref = refs_by_id[resolved]
                    best_score = 0.9

            # ------------------------------------------------
            # 3. Title + author + year similarity
            # ------------------------------------------------

            if best_ref is None:

                for ref in candidate_refs:

                    t_sim = title_similarity(bib, ref)
                    a_sim = author_overlap(bib, ref)
                    y_diff = year_distance(bib, ref)

                    score = (
                        t_sim * 0.7
                        + a_sim * 0.2
                        + (
                            0.1
                            if 0 <= y_diff <= 1
                            else 0.0
                        )
                    )

                    if score > best_score:
                        best_score = score
                        best_ref = ref

                if best_score < 0.5:
                    best_ref = None
                    best_score = 0.0

            # ------------------------------------------------
            # Chuẩn bị dữ liệu CSV
            # ------------------------------------------------

            suggested_id = (
                _ref_id(best_ref)
                if best_ref
                else ""
            )

            suggested_title = (
                _ref_title(best_ref)
                if best_ref
                else ""
            )

            suggested_score = (
                f"{best_score:.2f}"
                if best_ref
                else ""
            )

            # Dùng bib_title gốc làm nội dung hiển thị
            bib_title_display = str(
                bib.get("bib_title")
            ).strip()

            authors = bib.get("authors") or []

            if isinstance(authors, str):
                authors = [authors]

            writer.writerow({
                "bibtex_id": _bibtex_id(
                    bib,
                    arxiv_id,
                ),
                "citation_key": str(
                    bib.get("citation_key") or ""
                ),
                "bib_title": bib_title_display,
                "bib_authors": "; ".join(
                    str(author)
                    for author in authors
                ),
                "bib_year": str(
                    bib.get("year") or ""
                ),
                "bib_doi": str(
                    bib.get("doi") or ""
                ),
                "bib_raw": str(
                    bib.get("bib_raw") or ""
                ),
                "suggested_ref_arxiv_id": suggested_id,
                "suggested_ref_title": suggested_title,
                "suggested_score": suggested_score,
                "groundtruth_arxiv_id": "",
                "is_verified": "NO",
                "note": "",
            })

            exported_count += 1

    print(
        f"[INFO] Đã xuất {exported_count} BibTeX entries "
        f"có bib_title cho {arxiv_id}."
    )

    return output_csv


# ============================================================
# 5. IMPORT MANUAL LABELS
# ============================================================

def import_manual_csv(
    csv_path: Path,
    arxiv_id: str,
    labels_dir: Path | None = None,
    *,
    require_verified: bool = True,
) -> Path:
    """
    Import manual CSV -> JSON.

    Quy tắc:
    1. Nếu người dùng tự điền groundtruth_arxiv_id:
       chấp nhận trực tiếp, không cần is_verified=YES.

    2. Nếu groundtruth trống:
       chỉ lấy suggested_ref_arxiv_id khi is_verified=YES.

    3. Nếu không xác định được groundtruth:
       bỏ qua dòng, không lưu groundtruth=None.
    """

    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy CSV: {csv_path}"
        )

    labels_dir = labels_dir or (DATA_DIR / "labels")
    labels_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = []
    skipped_unverified = 0
    skipped_missing_gt = 0
    seen_keys: set[str] = set()

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(
                f"CSV không có header: {csv_path.name}"
            )

        required_columns = {
            "citation_key",
            "groundtruth_arxiv_id",
        }

        missing_columns = (
            required_columns - set(reader.fieldnames)
        )

        if missing_columns:
            raise ValueError(
                "CSV thiếu các cột bắt buộc: "
                + ", ".join(sorted(missing_columns))
            )

        has_verified = (
            "is_verified" in reader.fieldnames
        )

        for record in reader:

            key = (
                record.get("citation_key") or ""
            ).strip()

            if not key:
                continue

            # Tránh import trùng citation_key
            if key in seen_keys:
                continue

            verified = (
                record.get("is_verified") or ""
            ).strip().upper()

            # Chỉ import dòng đã xác nhận nếu require_verified=True
            if require_verified and has_verified and verified != "YES":
                skipped_unverified += 1
                continue
            # --------------------------------------------
            # Ưu tiên 1: groundtruth do người dùng nhập
            # --------------------------------------------

            gt = (
                record.get("groundtruth_arxiv_id") or ""
            ).strip()

            invalid_values = {
                "none",
                "null",
                "na",
                "n/a",
                "-",
            }

            gt_id = (
                gt
                if gt and gt.lower() not in invalid_values
                else None
            )

            # --------------------------------------------
            # Ưu tiên 2: dùng suggested nếu đã xác nhận
            # --------------------------------------------

            if not gt_id:

                if (
                    require_verified
                    and has_verified
                    and verified != "YES"
                ):
                    skipped_unverified += 1
                    continue

                if verified == "YES" or not require_verified:

                    suggested = (
                        record.get(
                            "suggested_ref_arxiv_id"
                        ) or ""
                    ).strip()

                    if (
                        suggested
                        and suggested.lower()
                        not in invalid_values
                    ):
                        gt_id = suggested

            # --------------------------------------------
            # Không có groundtruth -> không import
            # --------------------------------------------

            if not gt_id:
                skipped_missing_gt += 1
                continue

            rows.append({
                "citation_key": key,
                "groundtruth_arxiv_id": gt_id,
                "source": "manual",
            })

            seen_keys.add(key)

    if not rows:
        raise ValueError(
            f"Không có nhãn hợp lệ trong {csv_path.name}. "
            "Hãy điền groundtruth_arxiv_id hoặc xác nhận "
            "suggested_ref_arxiv_id bằng is_verified=YES."
        )

    # --------------------------------------------
    # Thông báo thống kê import
    # --------------------------------------------

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    print(f"[INFO] Imported labels: {len(rows)}")

    if skipped_unverified:
        print(
            f"[WARN] Bỏ qua {skipped_unverified} dòng "
            "chưa xác nhận."
        )

    if skipped_missing_gt:
        print(
            f"[WARN] Bỏ qua {skipped_missing_gt} dòng "
            "không có groundtruth."
        )

    # --------------------------------------------
    # Ghi JSON
    # --------------------------------------------

    output = (
        labels_dir
        / "manual"
        / f"{arxiv_id}.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_json(output, rows)

    return output


# ============================================================
# 6. TỔNG HỢP TIẾN ĐỘ GÁN NHÃN
# ============================================================

def summarize_team_labels(
    labels_dir: Path | None = None,
    n_publications_total: int = 50,
    k: int = 1,
) -> dict[str, Any]:
    """Tổng hợp manual labels và automatic labels."""

    labels_dir = labels_dir or (DATA_DIR / "labels")
    labels = load_labels(labels_dir)

    summary = {
        "n_manual_papers": 0,
        "n_manual_entries": 0,
        "manual_details": {},
        "n_auto_papers": 0,
        "n_auto_entries": 0,
        "quota_status": "UNKNOWN",
        "k": k,
    }

    for pid, entries in labels.items():

        manual_count = sum(
            1
            for entry in entries
            if entry.get("source") == "manual"
        )

        auto_count = sum(
            1
            for entry in entries
            if entry.get("source") == "auto"
        )

        if manual_count:
            summary["n_manual_papers"] += 1
            summary["n_manual_entries"] += manual_count
            summary["manual_details"][pid] = manual_count

        if auto_count:
            summary["n_auto_papers"] += 1
            summary["n_auto_entries"] += auto_count

    try:
        validate_label_quota(
            labels,
            n_publications_total,
            k=k,
        )

        summary["quota_status"] = "PASSED"

    except Exception as exc:
        summary["quota_status"] = f"FAILED: {exc}"

    return summary


# ============================================================
# 7. COMMAND LINE
# ============================================================

def main() -> None:

    import argparse

    for stream in (
        sys.stdout,
        sys.stderr,
    ):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="M3 Manual Labeling Tool"
    )

    parser.add_argument(
        "--find-candidates",
        action="store_true",
    )

    parser.add_argument(
        "--export-template",
        type=str,
    )

    parser.add_argument(
        "--import-csv",
        type=str,
    )

    parser.add_argument(
        "--paper-id",
        type=str,
    )

    parser.add_argument(
        "--allow-unverified",
        action="store_true",
    )

    parser.add_argument(
        "--summary",
        action="store_true",
    )

    parser.add_argument(
        "--bibtex-path",
        type=Path,
        help=(
            "Đường dẫn bibtex.json, bibtex.jsonl "
            "hoặc ZIP chứa chúng"
        ),
    )

    parser.add_argument(
        "--references-path",
        type=Path,
        help="Đường dẫn references.json hoặc references.jsonl",
    )

    parser.add_argument(
        "--k",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--n-publications",
        type=int,
        default=50,
    )

    args = parser.parse_args()

    if (
        args.find_candidates
        or args.export_template
    ):
        if (
            not args.bibtex_path
            or not args.references_path
        ):
            parser.error(
                "Cần cung cấp --bibtex-path "
                "và --references-path."
            )

    # --------------------------------------------
    # Tìm publications đủ điều kiện
    # --------------------------------------------

    if args.find_candidates:

        candidates = find_candidate_manual_papers(
            args.bibtex_path,
            args.references_path,
        )

        print(
            f"Tìm thấy {len(candidates)} bài đủ điều kiện:"
        )

        for pid, bib_count, ref_count in candidates[:15]:

            print(
                f"- {pid}: "
                f"{bib_count} BibTeX có bib_title | "
                f"{ref_count} References"
            )

    # --------------------------------------------
    # Xuất manual template
    # --------------------------------------------

    elif args.export_template:

        pid = args.export_template

        output = (
            DATA_DIR
            / "labels"
            / "manual"
            / f"{pid}.csv"
        )

        export_manual_template(
            pid,
            output,
            args.bibtex_path,
            args.references_path,
        )

        print(f"Đã xuất CSV: {output}")

    # --------------------------------------------
    # Import manual labels
    # --------------------------------------------

    elif args.import_csv:

        csv_path = Path(args.import_csv)

        pid = (
            args.paper_id
            or csv_path.stem
        )

        output = import_manual_csv(
            csv_path,
            pid,
            require_verified=not args.allow_unverified,
        )

        print(f"Đã import labels: {output}")

    # --------------------------------------------
    # Tổng hợp quota
    # --------------------------------------------

    elif args.summary:

        result = summarize_team_labels(
            n_publications_total=args.n_publications,
            k=args.k,
        )

        print("=== BÁO CÁO GÁN NHÃN ===")

        print(
            f"Manual papers: "
            f"{result['n_manual_papers']}"
        )

        print(
            f"Manual entries: "
            f"{result['n_manual_entries']}"
        )

        print(
            f"Manual details: "
            f"{result['manual_details']}"
        )

        print(
            f"Auto papers: "
            f"{result['n_auto_papers']}"
        )

        print(
            f"Auto entries: "
            f"{result['n_auto_entries']}"
        )

        print(
            f"Quota: "
            f"{result['quota_status']}"
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

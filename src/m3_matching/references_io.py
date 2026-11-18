"""Gắn DOI từ M1 vào bảng references (bảng 6 cột chuẩn HF không có DOI).

M1 ghi hai thứ:
  - tables/references.json                : 6 cột, chỉ ref CÓ arXiv ID (pool của M3)
  - tables/references_raw_response.json   : record đầy đủ (ref_doi, external_ids),
                                            kể cả ref không có arXiv ID

M3 vẫn dùng references.json làm pool ứng viên (không đổi). Module này chỉ
BỔ SUNG ``ref_doi`` cho từng dòng của pool bằng cách tra (arxiv_id, ref_s2_id)
trong file đầy đủ. Không có file đầy đủ (hoặc paper crawl bằng code cũ) thì
dòng giữ nguyên, ``doi_match`` = 0 như trước.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

RAW_REFERENCES_NAME = "references_raw_response.json"


def _doi_of(record: dict[str, Any]) -> str | None:
    doi = record.get("ref_doi") or record.get("doi") or record.get("DOI")
    if not doi:
        for key in ("external_ids", "externalIds"):
            ids = record.get(key)
            if isinstance(ids, dict) and ids.get("DOI"):
                doi = ids["DOI"]
                break
    return str(doi).strip() if doi else None


def _read_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:  # JSONL mang đuôi .json
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def load_raw_reference_records(tables_dir: Path) -> list[dict[str, Any]]:
    """Đọc references_raw_response.json (nếu có). Thiếu file -> []."""
    path = Path(tables_dir) / RAW_REFERENCES_NAME
    if not path.is_file():
        return []
    try:
        return _read_records(path)
    except (OSError, ValueError) as exc:
        LOG.warning("Không đọc được %s: %s", path, exc)
        return []


def enrich_references_with_doi(
    references: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Trả list mới; thêm ``ref_doi`` cho dòng nào tra được. Không đổi số dòng."""
    lookup: dict[tuple[str, str], str] = {}
    for raw in raw_records:
        doi = _doi_of(raw)
        s2_id = str(raw.get("ref_s2_id") or "").strip()
        citing = str(raw.get("arxiv_id") or "").strip()
        if doi and s2_id and citing:
            lookup.setdefault((citing, s2_id), doi)

    out: list[dict[str, Any]] = []
    for ref in references:
        row = dict(ref)
        if not _doi_of(row):
            key = (str(row.get("arxiv_id") or "").strip(),
                   str(row.get("ref_s2_id") or "").strip())
            if key in lookup:
                row["ref_doi"] = lookup[key]
        out.append(row)
    return out


def enrich_from_tables_dir(
    references: list[dict[str, Any]], tables_dir: Path,
) -> list[dict[str, Any]]:
    """Tiện dụng: đọc file đầy đủ cạnh references.json rồi gắn DOI."""
    raw = load_raw_reference_records(tables_dir)
    if not raw:
        return references
    enriched = enrich_references_with_doi(references, raw)
    n = sum(1 for r in enriched if r.get("ref_doi"))
    LOG.info("Gắn DOI cho %d / %d references (từ %s).",
             n, len(enriched), RAW_REFERENCES_NAME)
    return enriched

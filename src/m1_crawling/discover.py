"""
Entry discovery: resolve assigned arXiv IDs → metadata + số version.

Đề: KHÔNG harvest cả arXiv. Graded part là resolve ID được giao và liệt kê
mọi version. Toolbox: arXiv API (chính), OAI-PMH, Kaggle snapshot (tùy chọn).

arxiv.py ≥ 4.0: dùng Client().results(Search(...)), KHÔNG search.results()
và KHÔNG Result.download_source() (đã bị gỡ).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperMeta:
    """Metadata một publication sau khi lookup API (latest version)."""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str = ""
    latest_version: int = 1
    submission_date: str = ""  # ISO, version 1 / published
    revised_dates: list[str] = field(default_factory=list)
    venue: str | None = None
    categories: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def fetch_paper_by_id(arxiv_id: str) -> PaperMeta:
    """
    Lookup một ID qua arXiv API (`id_list`).

    Cần code bên trong:
    - arxiv.Search(id_list=[arxiv_id]) + arxiv.Client().results(search).
    - Tôn trọng ARXIV_MIN_DELAY_SEC (3s) — Client mặc định đã delay, vẫn log.
    - paper.id thường là 'http://arxiv.org/abs/2310.12345v4' → parse latest_version.
    - published ~ submission_date; updated + version history nếu API trả.
    - Nếu paper không tồn tại: raise rõ ràng để pipeline ghi fail, không im lặng.
    """
    raise NotImplementedError("TODO(M1): fetch_paper_by_id")


def list_versions(meta: PaperMeta) -> list[int]:
    """
    Mọi version phải crawl: [1, 2, ..., latest].

    Cần code bên trong:
    - Nếu latest_version = 4 → [1, 2, 3, 4].
    - Paper chỉ submit 1 lần → [1] (đề: suffice with v1).
    """
    raise NotImplementedError("TODO(M1): list_versions")


def harvest_oai_pmh_optional(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """
    TÙY CHỌN (toolbox, không bắt buộc cho assigned range).

    Cần code bên trong nếu nhóm muốn so sánh phương pháp trong report:
    - sickle.Sickle(OAI_PMH_ENDPOINT).ListRecords(metadataPrefix='arXiv', ...).
    - Endpoint mới: https://oaipmh.arxiv.org/oai (cũ export.arxiv.org/oai2 đã retire).
    - Resumption token hết hạn theo ngày — harvest lớn phải resume từ state đã lưu.
    """
    raise NotImplementedError("TODO(M1, optional): harvest_oai_pmh_optional")


def load_kaggle_metadata_optional(file_path: str, keyword: str) -> object:
    """
    TÙY CHỌN: Cornell arXiv metadata JSONL trên Kaggle (không gọi API).

    Cần code bên trong nếu dùng cho exploratory / report:
    - Đọc từng dòng json.loads → DataFrame.
    - Filter title.contains(keyword, case=False).
    - KHÔNG thay thế bước resolve assigned IDs (phần được chấm).
    """
    raise NotImplementedError("TODO(M1, optional): load_kaggle_metadata_optional")

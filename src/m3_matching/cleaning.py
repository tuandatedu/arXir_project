"""
Text preprocessing thêm cho matching (sau M2).

Chuẩn hóa tiêu đề, tác giả, năm và DOI cho hai bảng bibtex và references
để phục vụ so sánh chuỗi, trích xuất đặc trưng và gán nhãn tự động.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Các stopwords tiếng Anh phổ biến trong tiêu đề học thuật
TITLE_STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were",
    "its", "via", "using", "towards", "based"
}

_YEAR_REGEX = re.compile(r"\b(19\d\d|20\d\d)\b")
_LATEX_CMD_REGEX = re.compile(r"\\[a-zA-Z]+(\[[^\]]*\])?(\{([^}]*)\})?")


def _strip_accents(text: str) -> str:
    """Chuyển ký tự unicode có dấu về dạng ASCII không dấu."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _clean_latex_text(text: str) -> str:
    """Loại bỏ markup LaTeX phổ biến trong tiêu đề BibTeX."""
    if not text:
        return ""
    # Đổi các ký tự escaped phổ biến
    text = text.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_")
    text = text.replace(r"\$", "$").replace(r"\#", "#")
    text = text.replace("&amp;", "&")
    # Bỏ các cặp ngoặc nhọn nhóm trong BibTeX: {{Title}} -> Title
    text = re.sub(r"[{}]", " ", text)
    # Bỏ command latex dạng \command hoặc \command{arg}
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    # Bỏ math inline $...$
    text = re.sub(r"\$[^$]*\$", " ", text)
    return text


def normalize_title(title: str, remove_stopwords: bool = False) -> str:
    """
    Chuẩn hóa tiêu đề bài báo:
    - Bỏ markup LaTeX, công thức toán inline
    - Bỏ dấu tiếng Việt / unicode accents về ASCII
    - Lowercase, loại bỏ dấu câu (punctuation) và khoảng trắng thừa
    - (Tùy chọn) Bỏ stop words tiếng Anh
    """
    if not title:
        return ""
    text = _clean_latex_text(str(title))
    text = _strip_accents(text).lower()
    # Chỉ giữ lại chữ cái và số
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = text.split()
    if remove_stopwords:
        words = [w for w in words if w not in TITLE_STOPWORDS]
    return " ".join(words)


def _parse_single_author(author_str: str) -> str:
    """
    Chuẩn hóa 1 tên tác giả về dạng canonical: 'lastname, first_initial'.
    Hỗ trợ cả dạng 'Vaswani, Ashish' và 'Ashish Vaswani'.
    """
    cleaned = _strip_accents(_clean_latex_text(author_str)).strip().lower()
    # Loại bỏ et al., others nếu nằm trong chuỗi tên
    cleaned = re.sub(r"\b(et\s+al\.?|others)\b", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"[^a-z\s,]", "", cleaned).strip()
    if not cleaned:
        return ""
    
    if "," in cleaned:
        # Dạng: Lastname, Firstname Middle
        parts = [p.strip() for p in cleaned.split(",", 1)]
        last = parts[0]
        first = parts[1] if len(parts) > 1 else ""
        initial = first[0] if first else ""
    else:
        # Dạng: Firstname Middle Lastname
        tokens = cleaned.split()
        if len(tokens) == 1:
            last = tokens[0]
            initial = ""
        else:
            last = tokens[-1]
            initial = tokens[0][0] if tokens[0] else ""

    return f"{last}, {initial}".strip(", ") if last else ""


def normalize_authors(authors: list[str] | str) -> list[str]:
    """
    Chuẩn hóa danh sách tác giả về dạng canonical 'lastname, initial'.
    - Xử lý cả list[str] và chuỗi ngăn cách bởi ' and '
    - Bỏ 'et al.', loại bỏ khoảng trắng thừa
    """
    if not authors:
        return []

    raw_list: list[str] = []
    if isinstance(authors, str):
        # Tách chuỗi theo ' and ' hoặc ';'
        chunks = re.split(r"\s+and\s+|;", authors, flags=re.IGNORECASE)
        raw_list.extend(chunks)
    elif isinstance(authors, (list, tuple)):
        for item in authors:
            if isinstance(item, str):
                if " and " in item.lower():
                    raw_list.extend(re.split(r"\s+and\s+", item, flags=re.IGNORECASE))
                else:
                    raw_list.append(item)

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        raw_str = raw.strip()
        if not raw_str or raw_str.lower() in ("et al.", "et al", "others"):
            continue
        parsed = _parse_single_author(raw_str)
        if parsed and parsed not in seen:
            seen.add(parsed)
            normalized.append(parsed)

    return normalized


def normalize_year(value: object) -> int | None:
    """
    Parse năm công bố từ int / '2017' / ISO date '2017-06-12'.
    Nếu thất bại hoặc ngoài dải [1800, 2100] -> trả về None.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    
    str_val = str(value).strip()
    match = _YEAR_REGEX.search(str_val)
    if match:
        year = int(match.group(1))
        return year if 1800 <= year <= 2100 else None
    return None


_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


def normalize_doi(value: object) -> str | None:
    """
    Chuẩn hóa DOI về dạng trần (không tiền tố URL/`doi:`), lowercase.

    Nhờ vậy `https://doi.org/10.1145/ABC` và `doi:10.1145/abc` được coi là
    cùng một DOI khi so khớp. Trả về None nếu rỗng/không có.
    """
    if value is None:
        return None
    doi = str(value).strip().lower()
    if not doi:
        return None
    for prefix in _DOI_PREFIXES:
        if doi.startswith(prefix):
            doi = doi[len(prefix):].strip()
    doi = doi.strip(" .,;")
    return doi or None


def prepare_bibtex_record(row: dict[str, Any]) -> dict[str, Any]:
    """
    Thêm các trường chuẩn hóa *_norm cho 1 BibTeX row (không sửa bảng gốc).
    Bao gồm:
    - title_norm: tiêu đề sau khi làm sạch
    - authors_norm: danh sách tác giả canonical
    - year_norm: năm integer hoặc None
    - doi_norm: DOI chữ thường, bỏ tiền tố https://doi.org/ nếu có
    """
    record = dict(row)
    record["title_norm"] = normalize_title(row.get("title") or "")
    record["authors_norm"] = normalize_authors(row.get("authors") or [])
    record["year_norm"] = normalize_year(row.get("year"))
    record["doi_norm"] = normalize_doi(row.get("doi"))

    return record


def prepare_reference_record(row: dict[str, Any]) -> dict[str, Any]:
    """
    Thêm các trường chuẩn hóa *_norm cho 1 crawled reference (có arXiv ID).
    Bao gồm:
    - title_norm: ref_title sau khi làm sạch
    - authors_norm: ref_authors canonical
    - year_norm: năm lấy từ ref_submission_date hoặc field year
    - doi_norm: DOI đã chuẩn hóa (nếu nguồn crawl có DOI)
    - ref_arxiv_id_norm: arXiv ID chuẩn hóa
    """
    record = dict(row)
    ref_title = row.get("ref_title") or row.get("title") or ""
    record["title_norm"] = normalize_title(ref_title)

    ref_authors = row.get("ref_authors") or row.get("authors") or []
    record["authors_norm"] = normalize_authors(ref_authors)

    # Thử lấy year từ ref_submission_date hoặc year trực tiếp
    date_val = row.get("ref_submission_date") or row.get("year")
    record["year_norm"] = normalize_year(date_val)

    # DOI có thể nằm ở nhiều tên field tùy nguồn crawl (M1 lưu externalIds)
    raw_doi = row.get("doi") or row.get("ref_doi") or row.get("DOI")
    if not raw_doi and isinstance(row.get("externalIds"), dict):
        raw_doi = row["externalIds"].get("DOI")
    record["doi_norm"] = normalize_doi(raw_doi)

    ref_arxiv_id = str(row.get("ref_arxiv_id") or "").strip()
    record["ref_arxiv_id_norm"] = ref_arxiv_id

    return record

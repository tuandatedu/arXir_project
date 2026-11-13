"""
Text preprocessing thêm cho matching (sau M2).

Chuẩn hóa tiêu đề, tác giả, năm và DOI cho hai bảng bibtex và references
để phục vụ so sánh chuỗi, trích xuất đặc trưng và gán nhãn tự động.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.common.ids import normalize_arxiv_id

# Các stopwords tiếng Anh phổ biến trong tiêu đề học thuật
TITLE_STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were",
    "its", "via", "using", "towards", "based"
}

_YEAR_REGEX = re.compile(r"\b(19\d\d|20\d\d)\b")

# Đuôi metadata bị dính vào title khi trích BibTeX (không thuộc tiêu đề)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_ARXIV_PREPRINT_TAIL_RE = re.compile(
    r"(?:^|[.;]\s+)\s*arxiv\s*preprint\b.*$", re.I
)
_ARXIV_ID_TAIL_RE = re.compile(
    r"(?:^|[.;]\s+)\s*arxiv:\s*\d{4}\.\d{4,5}(?:v\d+)?.*$", re.I
)
_DOI_TAIL_RE = re.compile(r"(?:^|[.;]\s+)\s*doi:\s*\S+.*$", re.I)

# Math inline: giữ phần nội dung thay vì xóa cả cụm (Top-$k$ -> Top k)
_MATH_DOLLAR_RE = re.compile(r"\$([^$]+)\$")
_MATH_PAREN_RE = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", re.S)

# Accent LaTeX: \'{e}, \"{o}, \^{a}, \`{a}, \~{n}, \={a}, \.{z}
_SINGLE_CHAR_ACCENT_RE = re.compile(r"""\\([`'^"~=.])\s*\{?([A-Za-z])\}?""")
# Accent LaTeX dạng lệnh chữ: \c{c}, \v{s}, \u{a}, \H{o}, \r{a}, \k{a}, ...
_WORD_ACCENT_RE = re.compile(r"\\([cHvurktbdD])\s*\{([A-Za-z]+)\}")

# Tiền tố họ phổ biến cần giữ chung với họ khi tên không có dấu phẩy:
# "Jan van der Berg" và "van der Berg, Jan" phải cho cùng kết quả.
_NAME_PARTICLES = {
    "van", "von", "vom", "der", "den", "de", "del", "della", "delle",
    "di", "da", "das", "dos", "du", "la", "le", "ter", "ten", "zu",
    "bin", "al", "el",
}


def _strip_accents(text: str) -> str:
    """Chuyển ký tự unicode có dấu về dạng ASCII không dấu."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _decode_latex_accents(text: str) -> str:
    """
    Giải mã accent LaTeX về ký tự gốc trước khi bỏ ngoặc nhọn.

    Ví dụ: ``Schr\\"{o}dinger`` -> ``Schrodinger`` (không phải ``schr o dinger``).
    """
    text = _SINGLE_CHAR_ACCENT_RE.sub(r"\2", text)
    text = _WORD_ACCENT_RE.sub(r"\2", text)
    return text


def _strip_citation_tails(text: str) -> str:
    """Bỏ URL/DOI/arXiv preprint bị dính vào cuối tiêu đề khi parse BibTeX."""
    if not text:
        return ""
    text = _URL_RE.sub(" ", text)
    text = _ARXIV_PREPRINT_TAIL_RE.sub(" ", text)
    text = _ARXIV_ID_TAIL_RE.sub(" ", text)
    text = _DOI_TAIL_RE.sub(" ", text)
    return text


def _clean_latex_text(text: str) -> str:
    """Loại bỏ markup LaTeX phổ biến trong tiêu đề BibTeX."""
    if not text:
        return ""
    # Đổi các ký tự escaped phổ biến
    text = text.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_")
    text = text.replace(r"\$", "$").replace(r"\#", "#")
    text = text.replace("&amp;", "&").replace("\u00a0", " ").replace("~", " ")
    # Giải mã accent trước khi ngoặc nhọn bị thay bằng khoảng trắng
    text = _decode_latex_accents(text)
    # Bỏ thẻ HTML (một số reference crawl về còn <i>, <sub>...)
    text = _HTML_TAG_RE.sub(" ", text)
    # Giữ nội dung math (Top-$k$ -> Top k) rồi bỏ dấu phân cách
    text = _MATH_PAREN_RE.sub(
        lambda m: f" {m.group(1) or m.group(2) or ''} ", text
    )
    text = _MATH_DOLLAR_RE.sub(r" \1 ", text)
    text = text.replace("$", " ")
    # Bỏ command latex dạng \command hoặc \command{arg}
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    # Bỏ các cặp ngoặc nhọn nhóm trong BibTeX: {{Title}} -> Title
    text = re.sub(r"[{}]", " ", text)
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
    text = _strip_citation_tails(str(title))
    text = _clean_latex_text(text)
    # NFKC gộp ligature/full-width (ﬁ -> fi) trước khi bỏ dấu
    text = unicodedata.normalize("NFKC", text)
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
        # Dạng: Lastname, Firstname Middle (họ có thể gồm nhiều từ)
        parts = [p.strip() for p in cleaned.split(",", 1)]
        last = re.sub(r"\s+", " ", parts[0]).strip()
        first = parts[1] if len(parts) > 1 else ""
        initial = first[0] if first else ""
    else:
        # Dạng: Firstname Middle Lastname
        tokens = cleaned.split()
        if len(tokens) == 1:
            last = tokens[0]
            initial = ""
        elif tokens[0] in _NAME_PARTICLES:
            # Chuỗi chỉ có họ kèm tiền tố, ví dụ "van der Berg"
            last = " ".join(tokens)
            initial = ""
        else:
            # Giữ tiền tố họ dính với họ: "Jan van der Berg" -> "van der berg"
            particle_idx = next(
                (i for i, token in enumerate(tokens) if i > 0 and token in _NAME_PARTICLES),
                None,
            )
            if particle_idx is not None:
                last = " ".join(tokens[particle_idx:])
                initial = tokens[0][0]
            else:
                last = tokens[-1]
                initial = tokens[0][0] if tokens[0] else ""

    last = re.sub(r"\s+", " ", last).strip()
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
        # Tách chuỗi theo ' and ', ';' hoặc xuống dòng
        chunks = re.split(r"\s+and\s+|[;\n]", authors, flags=re.IGNORECASE)
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


# ---------------------------------------------------------------------------
# Chuỗi trích dẫn kiểu ADS bị M2 nhét vào field authors (không có title):
#   "Abdurro'uf, Accetta, K., Aerts, C., et al.\\ 2022, , 259, 35. doi:10.3847/..."
# ---------------------------------------------------------------------------
_ADS_RE = re.compile(
    r"^(?P<authors>.*?)(?:,?\s*et\s+al\.)?\\?\s+(?P<year>(?:1[89]|20)\d{2})[a-z]?\s*,(?P<rest>.*)$",
    re.S,
)
# Token chỉ gồm initials: "K." / "T. C." / "J.-L."
_INITIALS_RE = re.compile(r"^(?:[A-Z]\.(?:-[A-Z]\.)?\s*)+$")
_ADS_DOI_RE = re.compile(r"doi:\s*(10\.\S+?)[.\s]*$", re.I)


def parse_ads_citation(raw: list | str | None) -> dict[str, Any] | None:
    """
    Tách chuỗi kiểu ADS thành {authors: list[str], year: int, doi: str | None}.

    Ví dụ: "Allende Prieto, C., Beers, T. C., et al.\\ 2006, , 636, 804. doi:10.1086/498131"
    -> authors ["Allende Prieto, C.", "Beers, T. C."], year 2006, doi "10.1086/498131".
    Trả None nếu chuỗi không đúng dạng (khi đó dùng heuristic khác).
    Chuỗi này không chứa tiêu đề bài báo, nên hàm không trả title.
    """
    if not raw:
        return None
    text = " ".join(str(a) for a in raw) if isinstance(raw, list) else str(raw)
    match = _ADS_RE.match(text.strip())
    if not match:
        return None

    authors: list[str] = []
    for token in (t.strip() for t in match.group("authors").split(",")):
        if not token:
            continue
        if _INITIALS_RE.match(token) and authors:
            authors[-1] += ", " + token  # "Accetta" + "K." -> "Accetta, K."
        else:
            authors.append(token)
    if not authors:
        return None

    doi_match = _ADS_DOI_RE.search(text)
    return {
        "authors": authors,
        "year": int(match.group("year")),
        "doi": doi_match.group(1) if doi_match else None,
    }


def _first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Trả về giá trị đầu tiên khác None/rỗng trong các tên field tương đương."""
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _extract_title_from_authors(authors_raw: list | str | None) -> str:
    """
    Heuristic: với BibTeX dạng misc (thường gặp trong LaTeX thủ công),
    M2 parser đôi khi nhét cả tiêu đề vào cuối mảng authors.

    Pattern điển hình:
        authors = ["Author A, Author B,", "Title of the Paper, Journal 123, 456 (2023)"]

    Thuật toán:
    1. Ghép toàn bộ authors thành 1 chuỗi.
    2. Tách ra các "đoạn" bởi dấu phẩy.
    3. Tìm đoạn đầu tiên dài > 20 ký tự mà không giống tên người
       (không chứa chữ viết hoa đơn lẻ kiểu "A. B." hoặc pattern họ tên).
    4. Dừng trước phần journal/số trang (số + ngoặc đơn ở cuối).

    Trả về chuỗi rỗng nếu không tìm được.
    """
    if not authors_raw:
        return ""

    # Ghép thành chuỗi
    if isinstance(authors_raw, list):
        combined = " ".join(str(a) for a in authors_raw)
    else:
        combined = str(authors_raw)

    combined = combined.strip()
    if not combined:
        return ""

    # Regex nhận dạng "phần tên người" kiểu "Lastname, F." hoặc "F. Lastname"
    _AUTHOR_FRAG_RE = re.compile(
        r"^[A-Z][a-z]+,\s+[A-Z]"             # Lastname, F
        r"|^[A-Z]\.\s*[A-Z][-a-z]+"           # F. Lastname
        r"|^[A-Z]{1,3}\.\s*[A-Z][-a-z]+"      # F.G. Lastname
        r"|et\s+al\.?"                          # et al
    )

    # Pattern "số trang / số tạp chí": "123, 456 (2023)" hoặc "vol. 12, no. 3"
    _JOURNAL_NUM_RE = re.compile(r"\b\d{1,4},\s*\d{1,4}\s*\(\d{4}\)")

    # Thử tách bằng dấu phẩy + xem từng đoạn
    # Nhưng title có thể chứa dấu phẩy nên dùng cách khác:
    # Tìm chuỗi dài bắt đầu bằng chữ hoa, không phải tên tác giả
    parts = re.split(r",\s*(?=[A-Z])", combined)

    candidate = ""
    for part in parts:
        part = part.strip()
        # Bỏ phần journal (chứa số trang)
        if _JOURNAL_NUM_RE.search(part):
            part = _JOURNAL_NUM_RE.sub("", part).strip()
        # Bỏ nếu giống tên người
        if _AUTHOR_FRAG_RE.match(part):
            continue
        # Bỏ nếu quá ngắn
        if len(part) < 15:
            continue
        # Nếu bắt đầu bằng chữ hoa và có nhiều từ → khả năng là title
        words = part.split()
        if words and words[0][0].isupper() and len(words) >= 3:
            candidate = part
            break

    # Dọn sạch
    if candidate:
        # Cắt bỏ từ ký tự số/journal ở cuối
        candidate = re.sub(r",?\s*[A-Z][a-z]+\.?\s+\d+.*$", "", candidate).strip()
        candidate = candidate.strip(".,;: ")

    return candidate if len(candidate) >= 10 else ""


def prepare_bibtex_record(row: dict[str, Any]) -> dict[str, Any]:
    """
    Thêm các trường chuẩn hóa *_norm cho 1 BibTeX row (không sửa bảng gốc).
    Bao gồm:
    - title_norm: tiêu đề sau khi làm sạch
    - authors_norm: danh sách tác giả canonical
    - year_norm: năm integer hoặc None
    - doi_norm: DOI chữ thường, bỏ tiền tố https://doi.org/ nếu có

    Khi title rỗng (M2 parse sai entry misc):
    1. Nếu field authors là chuỗi kiểu ADS ("A, B., et al.\\ 2022, , 259, 35. doi:..."):
       tách lại authors/year/doi; đặt title_missing=True và giữ chuỗi gốc ở bib_raw.
       Chuỗi này KHÔNG có tiêu đề nên title để rỗng, không bịa.
    2. Ngược lại: thử heuristic _extract_title_from_authors.
    """
    record = dict(row)

    raw_title = _first_present(row, ("title", "bib_title")) or ""

    if not raw_title:
        authors_raw = _first_present(row, ("authors", "bib_authors"))
        ads = parse_ads_citation(authors_raw)
        if ads:
            record["bib_raw"] = (
                " ".join(str(a) for a in authors_raw)
                if isinstance(authors_raw, list)
                else str(authors_raw)
            )
            record["authors"] = ads["authors"]
            record["title_missing"] = True
            if not _first_present(row, ("year", "bib_year")):
                record["year"] = ads["year"]
            if not _first_present(row, ("doi", "bib_doi")) and ads["doi"]:
                record["doi"] = ads["doi"]
        else:
            raw_title = _extract_title_from_authors(authors_raw)
            if raw_title:
                record["title"] = raw_title  # để bib_title hiện ra trong CSV

    record["title_norm"] = normalize_title(raw_title)
    record["authors_norm"] = normalize_authors(
        _first_present(record, ("authors", "bib_authors")) or []
    )
    record["year_norm"] = normalize_year(
        _first_present(record, ("year", "bib_year"))
    )
    record["doi_norm"] = normalize_doi(
        _first_present(record, ("doi", "bib_doi"))
    )

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

    raw_ref_id = str(row.get("ref_arxiv_id") or "").strip()
    if raw_ref_id:
        try:
            # Bỏ prefix arXiv: / URL và hậu tố version vN để so khớp ổn định.
            raw_ref_id = normalize_arxiv_id(raw_ref_id)
        except ValueError:
            # Giữ nguyên dữ liệu lạ (ví dụ ID giả trong demo) thay vì làm sập pipeline.
            pass
    record["ref_arxiv_id_norm"] = raw_ref_id

    return record
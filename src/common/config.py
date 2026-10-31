"""
Hằng số và đường dẫn làm việc của cả đồ án.

Đồ án: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/

Các giá trị dưới đây lấy từ đề (rate limit, endpoint, schema). Thành viên khác
chỉ việc import, không hard-code URL/delay rải rác trong pipeline.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Đường dẫn làm việc (local, không commit data/)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"

# Corpus thô M1: một folder / publication, ví dụ data/working/2310-12345/
WORKING_DIR = DATA_DIR / "working"

# Output bảng nội bộ (jsonl/parquet tạm) trước khi publish Hugging Face
TABLES_DIR = DATA_DIR / "tables"

# Dataset Hugging Face local (M3 copy lên Hub)
HF_EXPORT_DIR = DATA_DIR / "hf_dataset"

# File ID được Lab Instructors giao (một arXiv ID / dòng)
ASSIGNED_IDS_FILE = PROJECT_ROOT / "assigned_ids.txt"

# ---------------------------------------------------------------------------
# arXiv — Milestone 1
# ---------------------------------------------------------------------------
# Dùng mirror export, KHÔNG crawl arxiv.org (dễ bị 403).
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_SRC_MIRROR = "https://export.arxiv.org/src"  # /{arxiv_id} hoặc /{id}vN
OAI_PMH_ENDPOINT = "https://oaipmh.arxiv.org/oai"

# API etiquette: tối thiểu 3 giây giữa các request, một connection tại một thời điểm (kể cả khi xử lý bài concurrent).
ARXIV_MIN_DELAY_SEC = 3.0
ARXIV_USER_AGENT = "arXir-project/0.1 (HCMUS Intro-DS group; academic crawl)"

# Chỉ giữ các file này trong corpus (đề: extract, không sửa TeX).
KEPT_SOURCE_SUFFIXES = (".tex", ".bib")

# ---------------------------------------------------------------------------
# Semantic Scholar — Milestone 1 / dùng lại ở M3
# ---------------------------------------------------------------------------
S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
S2_FIELDS = (
    "references.title",
    "references.authors",
    "references.year",
    "references.publicationDate",
    "references.venue",
    "references.externalIds",
)
# Unauthenticated: 1 req/s và 100 req / 5 phút. API key (S2_API_KEY) ổn định hơn.
S2_MIN_DELAY_SEC = 1.0

# ---------------------------------------------------------------------------
# Hugging Face — Milestone 3 (6 bảng, Parquet sharded)
# ---------------------------------------------------------------------------
HF_TABLE_NAMES = (
    "papers",
    "references",
    "elements",
    "hierarchy",
    "bibtex",
    "predictions",
)

# ---------------------------------------------------------------------------
# Milestone 3 — ràng buộc labelling / split / metric
# ---------------------------------------------------------------------------
MIN_MANUAL_PUBLICATIONS = 5
MIN_LABELED_ENTRIES_PER_MANUAL_PAPER = 20
MIN_LABELED_ENTRIES_TOTAL = 100
MIN_AUTO_LABEL_FRACTION = 0.10  # ≥ 10% publications ngoài manual pool
MRR_K = 5
PREDICTION_PARTITIONS = ("train", "valid", "test")

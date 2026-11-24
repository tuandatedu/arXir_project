
from pathlib import Path
from collections import defaultdict
import random

import pandas as pd
import pyarrow.parquet as pq

# Đường dẫn dữ liệu
SOURCE = Path("data/m3/range_1/prepared_dataset/train_pairs.parquet")
OUTPUT = Path("data/m3/range_1/prepared_dataset/train_dev_sample.parquet")

KEYS = ["arxiv_id", "citation_key"]

# BƯỚC 1: Đếm số Positive của từng BibTeX query
positive_counts = defaultdict(int)

parquet = pq.ParquetFile(SOURCE)

for batch in parquet.iter_batches(
    batch_size=50000,
    columns=["arxiv_id", "citation_key", "label"],
):
    df = batch.to_pandas()
    grouped = df.groupby(KEYS)["label"].sum()

    for query_key, count in grouped.items():
        positive_counts[query_key] += int(count)

# Kiểm tra mỗi query có tối đa một Positive
assert all(v in (0, 1) for v in positive_counts.values())

positive_queries = [
    key for key, count in positive_counts.items() if count == 1
]

zero_positive_queries = [
    key for key, count in positive_counts.items() if count == 0
]

# BƯỚC 2: Chọn 10 queries từ mỗi nhóm
rng = random.Random(42)

selected = set(
    rng.sample(positive_queries, min(10, len(positive_queries)))
    + rng.sample(zero_positive_queries, min(10, len(zero_positive_queries)))
)

# BƯỚC 3: Đọc lại dữ liệu và giữ toàn bộ candidates
samples = []

for batch in pq.ParquetFile(SOURCE).iter_batches(batch_size=10000):
    df = batch.to_pandas()

    query_index = pd.MultiIndex.from_frame(df[KEYS])
    subset = df.loc[query_index.isin(selected)]

    if not subset.empty:
        samples.append(subset)

sample_df = pd.concat(samples, ignore_index=True)

# BƯỚC 4: Kiểm tra và lưu
assert sample_df.groupby(KEYS).ngroups == len(selected)
assert set(sample_df["partition"]) == {"train"}

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
sample_df.to_parquet(OUTPUT, index=False)

print("Sample file:", OUTPUT)
print("Total pairs:", len(sample_df))
print("Total queries:", sample_df.groupby(KEYS).ngroups)
print("Positive pairs:", int(sample_df["label"].sum()))
print("Negative pairs:", int((sample_df["label"] == 0).sum()))
print("Columns:", len(sample_df.columns))
print("SAMPLE READY")

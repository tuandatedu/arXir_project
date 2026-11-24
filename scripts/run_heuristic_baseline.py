import sys
import pandas as pd

DATA_PATH = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "data/m3/range_1/prepared_dataset/train_dev_sample.parquet"
)
QUERY_KEYS = ["arxiv_id", "citation_key"]

# Đọc Training mẫu
df = pd.read_parquet(DATA_PATH)

# Dùng độ tương đồng tiêu đề làm điểm xếp hạng
df["score"] = df["title_levenshtein"]

results = []

for (arxiv_id, citation_key), group in df.groupby(QUERY_KEYS):
    # Kiểm tra nhãn
    assert group["label"].sum() <= 1

    # Xếp hạng giảm dần theo score, lấy Top-5
    top5 = group.sort_values(
        "score", ascending=False, kind="mergesort"
    ).head(5)

    # Tính Reciprocal Rank
    rr = 0.0
    correct_rank = None

    for rank, label in enumerate(top5["label"], start=1):
        if label == 1:
            correct_rank = rank
            rr = 1.0 / rank
            break

    results.append({
        "arxiv_id": arxiv_id,
        "citation_key": citation_key,
        "correct_rank": correct_rank,
        "rr_at_5": rr,
    })

result_df = pd.DataFrame(results)
mrr = result_df["rr_at_5"].mean()

print("HEURISTIC BASELINE")
print("Total pairs:", len(df))
print("Total queries:", len(result_df))
print("Correct matches in Top-5:",
      result_df["correct_rank"].notna().sum())
print(f"MRR@5: {mrr:.6f}")
print("\nResults:")
print(result_df.to_string(index=False))
print("\nBASELINE COMPLETED")

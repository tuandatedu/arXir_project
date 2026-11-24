
import pandas as pd


def mrr_at_5(df):
    """
    Calculate MRR@5 for BibTeX-reference matching.

    Required columns:
        arxiv_id, citation_key, ref_arxiv_id, score, label

    Each query must have at most one positive candidate.
    Queries with no positive in Top-5 receive RR = 0.
    """
    query_keys = ["arxiv_id", "citation_key"]
    reciprocal_ranks = []

    for (arxiv_id, citation_key), group in df.groupby(query_keys):
        # Kiểm tra một query có tối đa một Positive
        if (group["label"] == 1).sum() > 1:
            raise ValueError(
                f"Multiple positives in query: {arxiv_id}, {citation_key}"
            )

        # Xếp ứng viên theo score từ cao xuống thấp
        ranked = group.sort_values(
            by="score",
            ascending=False,
            kind="mergesort",
        ).head(5)

        # Tìm vị trí reference đúng trong Top-5
        rr = 0.0

        for rank, label in enumerate(ranked["label"], start=1):
            if label == 1:
                rr = 1.0 / rank
                break

        reciprocal_ranks.append(rr)

        print(f"Query {citation_key}: RR@5 = {rr:.6f}")

    if not reciprocal_ranks:
        raise ValueError("Dataset contains no queries")

    return sum(reciprocal_ranks) / len(reciprocal_ranks)


# ----------------------------------------
# Dữ liệu giả lập để kiểm thử
# ----------------------------------------

rows = []


def add_query(citation_key, ranked_refs, correct_ref):
    for index, ref_id in enumerate(ranked_refs):
        rows.append({
            "arxiv_id": "paper_demo",
            "citation_key": citation_key,
            "ref_arxiv_id": ref_id,
            "score": len(ranked_refs) - index,
            "label": int(ref_id == correct_ref),
        })


# B1: Reference đúng ở Top 1
add_query(
    "B1",
    ["R3", "R1", "R5", "R2", "R4"],
    "R3",
)

# B2: Reference đúng ở Top 3
add_query(
    "B2",
    ["R4", "R2", "R8", "R7", "R1"],
    "R8",
)

# B3: Reference đúng ở Top 6 (ngoài Top-5)
add_query(
    "B3",
    ["R1", "R3", "R4", "R7", "R8", "R9"],
    "R9",
)

df = pd.DataFrame(rows)

result = mrr_at_5(df)

print("-------------------------")
print(f"MRR@5 = {result:.6f}")

# Tự động xác nhận kết quả đúng
assert abs(result - (4 / 9)) < 1e-9

print("TEST PASSED")


from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


# 14 features đầu vào của M3
FEATURES = [
    "title_levenshtein",
    "title_token_sort",
    "title_token_set",
    "title_jaccard",
    "title_exact",
    "title_len_diff_ratio",
    "author_jaccard",
    "author_first_match",
    "author_any_match",
    "year_diff",
    "year_exact",
    "year_missing",
    "doi_match",
    "cite_count",
]

DATA_PATH = Path(
    "data/m3/range_1/prepared_dataset/train_dev_sample.parquet"
)


def main():
    # Bước 1: Đọc dữ liệu
    df = pd.read_parquet(
        DATA_PATH,
        columns=FEATURES + ["label"]
    )

    # Bước 2: Tách X (features) và y (nhãn)
    X = df[FEATURES]
    y = df["label"].astype(int)

    # Kiểm tra dữ liệu trước khi train
    if not np.isfinite(X.to_numpy(dtype=float)).all():
        raise ValueError("Features chứa NaN hoặc giá trị vô hạn.")

    if set(y.unique()) != {0, 1}:
        raise ValueError("Dữ liệu phải chứa cả nhãn 0 và 1.")

    print("=== DU LIEU TRAIN ===")
    print("X:", X.shape)
    print("y:", y.shape)
    print("Phan bo nhan:")
    print(y.value_counts().sort_index())

    # Bước 3: Tạo Pipeline
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            class_weight=None,
            max_iter=1000,
            random_state=42
        )
    )

    # Bước 4: Huấn luyện LR
    model.fit(X, y)

    lr = model.named_steps["logisticregression"]

    print("\n=== KET QUA HUAN LUYEN ===")
    print("So features:", lr.n_features_in_)
    print("So vong lap:", lr.n_iter_[0])
    print("Cac nhan:", lr.classes_)

    # Bước 5: Lấy điểm dự đoán của nhãn 1
    positive_col = list(lr.classes_).index(1)
    scores = model.predict_proba(X)[:, positive_col]

    print("\n=== 5 DIEM DU DOAN DAU TIEN ===")
    for i in range(5):
        print(
            f"Pair {i}: "
            f"score={scores[i]:.6f}, "
            f"label={y.iloc[i]}"
        )

    # Bước 6: Xem các trọng số LR đã học
    print("\n=== TRONG SO LOGISTIC REGRESSION ===")

    weights = sorted(
        zip(FEATURES, lr.coef_[0]),
        key=lambda item: abs(item[1]),
        reverse=True
    )

    for feature_name, weight in weights:
        print(f"{feature_name:25s}: {weight:+.6f}")

    print(f"\nIntercept: {lr.intercept_[0]:+.6f}")

    # Bước 7: Đánh giá LR trên Validation
    valid_path = Path(
        "data/m3/range_1/prepared_dataset/valid_pairs.parquet"
    )

    valid_df = pd.read_parquet(
        valid_path,
        columns=FEATURES + [
            "arxiv_id",
            "citation_key",
            "label"
        ]
    )

    X_valid = valid_df[FEATURES]

    # Chỉ dự đoán, KHÔNG fit lại trên Validation
    valid_df["score"] = model.predict_proba(X_valid)[:, positive_col]

    reciprocal_ranks = []
    positive_queries = 0
    top1_correct = 0

    # Mỗi BibTeX entry là một query
    for _, group in valid_df.groupby(
        ["arxiv_id", "citation_key"],
        sort=False
    ):
        # Xếp candidate theo score giảm dần, giữ thứ tự
        # gốc nếu có điểm bằng nhau
        ranked = group.sort_values(
            "score",
            ascending=False,
            kind="mergesort"
        )

        positive_positions = np.flatnonzero(
            ranked["label"].to_numpy() == 1
        )

        rr = 0.0

        if len(positive_positions) > 1:
            raise ValueError("Query có nhiều Positive!")

        if len(positive_positions) == 1:
            positive_queries += 1
            rank = int(positive_positions[0]) + 1

            if rank == 1:
                top1_correct += 1

            if rank <= 5:
                rr = 1.0 / rank

        reciprocal_ranks.append(rr)

    mrr_at_5 = np.mean(reciprocal_ranks)

    print("\n=== LR VALIDATION (THU NGHIEM) ===")
    print("Tong pairs:", len(valid_df))
    print("Tong queries:", len(reciprocal_ranks))
    print("Queries co Positive:", positive_queries)
    print("Positive dung Top 1:", top1_correct)
    print(f"MRR@5: {mrr_at_5:.6f}")



if __name__ == "__main__":
    main()

from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import csr_matrix


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "sephora_hybrid_lightfm.joblib"
)


def load_model():
    bundle = joblib.load(
        MODEL_PATH
    )

    model = bundle["model"]
    dataset = bundle["dataset"]

    (
        user_id_map,
        user_feature_map,
        item_id_map,
        item_feature_map,
    ) = dataset.mapping()

    return {
        "model": model,
        "dataset": dataset,
        "item_feature_matrix": bundle[
            "item_feature_matrix"
        ],
        "item_features": bundle[
            "item_features"
        ],
        "user_id_map": user_id_map,
        "user_feature_map": user_feature_map,
        "item_id_map": item_id_map,
        "item_feature_map": item_feature_map,
    }


def normalize_profile_value(value):
    if value is None:
        return "unknown"

    value = str(
        value
    ).strip().lower()

    if not value:
        return "unknown"

    return " ".join(
        value.split()
    )


def build_new_user_feature_matrix(
    user_feature_map,
    skin_type="unknown",
    skin_tone="unknown",
    eye_color="unknown",
    hair_color="unknown",
):
    profile = {
        "skin_type": normalize_profile_value(
            skin_type
        ),
        "skin_tone": normalize_profile_value(
            skin_tone
        ),
        "eye_color": normalize_profile_value(
            eye_color
        ),
        "hair_color": normalize_profile_value(
            hair_color
        ),
    }

    feature_indices = []

    for feature_name, value in profile.items():
        token = (
            f"{feature_name}:{value}"
        )

        if token not in user_feature_map:
            fallback_token = (
                f"{feature_name}:unknown"
            )

            if fallback_token not in user_feature_map:
                continue

            token = fallback_token

        feature_indices.append(
            user_feature_map[token]
        )

    if not feature_indices:
        raise ValueError(
            "사용할 수 있는 사용자 프로필 feature가 없습니다."
        )

    feature_count = len(
        feature_indices
    )

    feature_weights = np.full(
        feature_count,
        1 / feature_count,
        dtype=np.float32,
    )

    return csr_matrix(
        (
            feature_weights,
            (
                np.zeros(
                    feature_count,
                    dtype=int,
                ),
                feature_indices,
            ),
        ),
        shape=(
            1,
            len(user_feature_map),
        ),
        dtype=np.float32,
    )


def _filter_candidate_products(
    candidate_product_ids,
    item_id_map,
):
    return [
        str(product_id)
        for product_id in candidate_product_ids
        if str(product_id) in item_id_map
    ]


def _build_ranked_results(
    product_ids,
    scores,
    top_n,
):
    results = [
        {
            "product_id": product_id,
            "lightfm_score": float(score),
        }
        for product_id, score in zip(
            product_ids,
            scores,
        )
    ]

    results.sort(
        key=lambda item: item[
            "lightfm_score"
        ],
        reverse=True,
    )

    return results[
        :int(top_n)
    ]


def recommend_from_candidates(
    user_id,
    candidate_product_ids,
    top_n=10,
):
    data = load_model()

    user_id_map = data[
        "user_id_map"
    ]
    item_id_map = data[
        "item_id_map"
    ]

    if user_id not in user_id_map:
        raise ValueError(
            f"LightFM에 없는 사용자입니다: {user_id}"
        )

    valid_products = (
        _filter_candidate_products(
            candidate_product_ids,
            item_id_map,
        )
    )

    if not valid_products:
        return []

    item_indices = np.array(
        [
            item_id_map[product_id]
            for product_id in valid_products
        ],
        dtype=np.int32,
    )

    user_indices = np.full(
        len(item_indices),
        user_id_map[user_id],
        dtype=np.int32,
    )

    scores = data["model"].predict(
        user_ids=user_indices,
        item_ids=item_indices,
        item_features=data[
            "item_feature_matrix"
        ],
        num_threads=1,
    )

    return _build_ranked_results(
        valid_products,
        scores,
        top_n,
    )


def recommend_new_user_from_candidates(
    candidate_product_ids,
    skin_type="unknown",
    skin_tone="unknown",
    eye_color="unknown",
    hair_color="unknown",
    top_n=10,
):
    data = load_model()

    item_id_map = data[
        "item_id_map"
    ]

    new_user_features = (
        build_new_user_feature_matrix(
            user_feature_map=data[
                "user_feature_map"
            ],
            skin_type=skin_type,
            skin_tone=skin_tone,
            eye_color=eye_color,
            hair_color=hair_color,
        )
    )

    valid_products = (
        _filter_candidate_products(
            candidate_product_ids,
            item_id_map,
        )
    )

    if not valid_products:
        return []

    item_indices = np.array(
        [
            item_id_map[product_id]
            for product_id in valid_products
        ],
        dtype=np.int32,
    )

    # 신규 사용자는 1행짜리 user feature matrix를 사용한다.
    user_indices = np.zeros(
        len(item_indices),
        dtype=np.int32,
    )

    scores = data["model"].predict(
        user_ids=user_indices,
        item_ids=item_indices,
        user_features=new_user_features,
        item_features=data[
            "item_feature_matrix"
        ],
        num_threads=1,
    )

    return _build_ranked_results(
        valid_products,
        scores,
        top_n,
    )


def main():
    data = load_model()

    print("LightFM 모델 로드 완료")
    print(
        "사용자 수:",
        len(data["user_id_map"]),
    )
    print(
        "상품 수:",
        len(data["item_id_map"]),
    )
    print(
        "사용자 feature 수:",
        len(data["user_feature_map"]),
    )


if __name__ == "__main__":
    main()

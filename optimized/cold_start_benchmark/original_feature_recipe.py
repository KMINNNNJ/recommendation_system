"""Original notebook feature recipe; called by compare_original.py.

K-core is applied before profile/row feature construction to avoid building
features that the notebook immediately discards. Included users/items retain
exactly the original feature definitions. No held-out reviews enter this function.
"""
import ast
import re
import numpy as np
import pandas as pd

def build_original_features(reviews_clean, interactions_clean, products):
    display = lambda *args, **kwargs: None
    def clean_text_value(value):
        if pd.isna(value):
            return "unknown"

        value = str(value).lower().strip()
        value = re.sub(r"\s+", " ", value)

        return value if value else "unknown"


    profile_cols = [
        "skin_type",
        "skin_tone",
        "eye_color",
        "hair_color",
    ]

    for col in profile_cols:
        reviews_clean[col] = (
            reviews_clean[col]
            .apply(clean_text_value)
        )

    print("[정리된 피부 타입]")
    display(
        reviews_clean["skin_type"]
        .value_counts()
        .head(20)
    )

    def k_core_filter(
        df,
        min_user_interactions=2,
        min_item_interactions=10
    ):
        filtered = df.copy()

        while True:
            before_count = len(filtered)

            # 긍정 상품을 2개 이상 가진 사용자만 유지
            user_counts = filtered["author_id"].value_counts()
            valid_users = user_counts[
                user_counts >= min_user_interactions
            ].index

            filtered = filtered[
                filtered["author_id"].isin(valid_users)
            ].copy()

            # 긍정 리뷰가 10개 이상인 상품만 유지
            item_counts = filtered["product_id"].value_counts()
            valid_items = item_counts[
                item_counts >= min_item_interactions
            ].index

            filtered = filtered[
                filtered["product_id"].isin(valid_items)
            ].copy()

            if len(filtered) == before_count:
                break

        return filtered

    hybrid_interactions = k_core_filter(
        interactions_clean,
        min_user_interactions=2,
        min_item_interactions=10,
    )

    print("상호작용 수:", len(hybrid_interactions))
    print("사용자 수:", hybrid_interactions["author_id"].nunique())
    print("상품 수:", hybrid_interactions["product_id"].nunique())

    interactions_clean = hybrid_interactions


    # 하이브리드 CF 학습에 포함된 사용자 목록
    hybrid_user_ids = interactions_clean[
        "author_id"
    ].unique()

    def mode_or_unknown(series):
        # unknown을 제외한 값 중 가장 많이 등장한 값 선택
        valid_values = series[
            series != "unknown"
        ]

        if valid_values.empty:
            return "unknown"

        return valid_values.mode().iloc[0]

    # 긍정 상호작용에 포함된 사용자의 리뷰만 가져옴
    user_profile_source = reviews_clean[
        reviews_clean["author_id"].isin(hybrid_user_ids)
    ].copy()

    # 사용자별 대표 피부 프로필 생성
    user_features = (
        user_profile_source
        .groupby("author_id", as_index=False)
        .agg(
            skin_type=(
                "skin_type",
                mode_or_unknown
            ),
            skin_tone=(
                "skin_tone",
                mode_or_unknown
            ),
            eye_color=(
                "eye_color",
                mode_or_unknown
            ),
            hair_color=(
                "hair_color",
                mode_or_unknown
            ),
        )
    )

    # 상호작용에 있는 모든 사용자가 포함되도록 연결
    user_features = pd.DataFrame(
        {"author_id": hybrid_user_ids}
    ).merge(
        user_features,
        on="author_id",
        how="left"
    )

    # 프로필 정보가 전혀 없는 사용자는 unknown 처리
    profile_cols = [
        "skin_type",
        "skin_tone",
        "eye_color",
        "hair_color",
    ]

    for col in profile_cols:
        user_features[col] = (
            user_features[col]
            .fillna("unknown")
        )

    print("사용자 피처 수:", len(user_features))
    display(user_features.head())

    def make_user_feature_tokens(row):
        return [
            f"skin_type:{row['skin_type']}",
            f"skin_tone:{row['skin_tone']}",
            f"eye_color:{row['eye_color']}",
            f"hair_color:{row['hair_color']}",
        ]

    user_features["feature_tokens"] = (
        user_features
        .apply(
            make_user_feature_tokens,
            axis=1
        )
    )

    display(
        user_features[
            [
                "author_id",
                "skin_type",
                "skin_tone",
                "feature_tokens",
            ]
        ].head()
    )

    # 하이브리드 CF 학습에 포함된 상품 목록
    hybrid_item_ids = interactions_clean[
        "product_id"
    ].unique()

    # 상품 하나당 한 행만 남김
    item_features = (
        products[
            products["product_id"].isin(hybrid_item_ids)
        ]
        .drop_duplicates(
            subset=["product_id"],
            keep="first"
        )
        .copy()
    )

    print("상품 피처 수:", len(item_features))
    print(
        "상호작용 상품 중 상품 정보가 없는 수:",
        len(hybrid_item_ids) - len(item_features)
    )

    def clean_product_value(value):
        if pd.isna(value):
            return "unknown"

        value = str(value).lower().strip()
        value = re.sub(r"\s+", " ", value)

        return value if value else "unknown"

    item_categorical_cols = [
        "brand_name",
        "primary_category",
        "secondary_category",
        "tertiary_category",
        "size",
        "variation_type",
        "variation_value",
        "variation_desc",
    ]

    for col in item_categorical_cols:
        item_features[col] = (
            item_features[col]
            .apply(clean_product_value)
        )

    display(
        item_features[
            [
                "product_id",
                "product_name",
                "brand_name",
                "primary_category",
                "secondary_category",
                "tertiary_category",
            ]
        ].head()
    )

    item_features["effective_price_usd"] = (
        item_features["sale_price_usd"]
        .fillna(item_features["price_usd"])
    )

    item_features["discount_usd"] = (
        item_features["price_usd"]
        - item_features["effective_price_usd"]
    ).clip(lower=0)

    item_features["price_band"] = pd.cut(
        item_features["effective_price_usd"],
        bins=[-np.inf, 15, 30, 50, 80, np.inf],
        labels=[
            "under_15",
            "15_to_30",
            "30_to_50",
            "50_to_80",
            "over_80",
        ]
    ).astype("string").fillna("unknown")

    display(
        item_features[
            [
                "product_name",
                "price_usd",
                "sale_price_usd",
                "effective_price_usd",
                "price_band",
            ]
        ].head()
    )

    item_boolean_cols = [
        "limited_edition",
        "new",
        "online_only",
        "out_of_stock",
        "sephora_exclusive",
    ]

    for col in item_boolean_cols:
        item_features[col] = (
            pd.to_numeric(
                item_features[col],
                errors="coerce"
            )
            .fillna(0)
            .astype("int8")
        )

    display(
        item_features[
            [
                "product_name",
                "limited_edition",
                "new",
                "online_only",
                "out_of_stock",
                "sephora_exclusive",
            ]
        ].head()
    )

    def parse_list_column(value):
        if pd.isna(value):
            return []

        try:
            parsed = ast.literal_eval(value)

            if isinstance(parsed, list):
                return parsed

            return [str(parsed)]

        except (ValueError, SyntaxError):
            return []

    def clean_tag(value):
        value = str(value).lower().strip()
        value = re.sub(r"\s+", " ", value)

        return value

    item_features["highlights_list"] = (
        item_features["highlights"]
        .apply(parse_list_column)
    )

    item_features["highlights_list"] = (
        item_features["highlights_list"]
        .apply(
            lambda tags: [
                clean_tag(tag)
                for tag in tags
                if clean_tag(tag)
            ]
        )
    )

    display(
        item_features[
            ["product_name", "highlights_list"]
        ].head()
    )

    def make_ingredient_list(raw_list):
        # 리스트 원소들을 하나의 문자열로 합침
        text = " ".join(
            str(value)
            for value in raw_list
        ).lower()

        # variation 설명 문구 제거
        text = re.sub(
            r"product variation \d+:?",
            "",
            text
        )

        # 쉼표 기준으로 성분 분리
        ingredients = [
            clean_tag(value)
            for value in text.split(",")
        ]

        # 너무 짧은 값, 빈 값 제거
        return [
            ingredient
            for ingredient in ingredients
            if len(ingredient) >= 2
        ]

    item_features["ingredients_list"] = (
        item_features["ingredients"]
        .apply(parse_list_column)
        .apply(make_ingredient_list)
    )

    display(
        item_features[
            ["product_name", "ingredients_list"]
        ].head()
    )

    def make_item_feature_tokens(row):
        tokens = [
            f"brand:{row['brand_name']}",
            f"primary_category:{row['primary_category']}",
            f"secondary_category:{row['secondary_category']}",
            f"tertiary_category:{row['tertiary_category']}",
            f"variation_type:{row['variation_type']}",
            f"price_band:{row['price_band']}",
        ]

        if row["limited_edition"] == 1:
            tokens.append("limited_edition")

        if row["new"] == 1:
            tokens.append("new")

        if row["online_only"] == 1:
            tokens.append("online_only")

        if row["sephora_exclusive"] == 1:
            tokens.append("sephora_exclusive")

        tokens.extend(
            f"highlight:{tag}"
            for tag in row["highlights_list"]
        )

        # 모든 성분 사용
        tokens.extend(
            f"ingredient:{ingredient}"
            for ingredient in row["ingredients_list"]
        )

        return tokens


    item_features["feature_tokens"] = (
        item_features
        .apply(make_item_feature_tokens, axis=1)
    )

    display(
        item_features[
            ["product_id", "product_name", "feature_tokens"]
        ].head()
    )

    hybrid_user_ids = hybrid_interactions["author_id"].unique()
    hybrid_item_ids = hybrid_interactions["product_id"].unique()

    user_features = user_features[
        user_features["author_id"].isin(hybrid_user_ids)
    ].copy()

    item_features = item_features[
        item_features["product_id"].isin(hybrid_item_ids)
    ].copy()

    print("사용자 피처 수:", len(user_features))
    print("상품 피처 수:", len(item_features))

    from lightfm import LightFM
    from lightfm.data import Dataset
    from itertools import chain

    all_user_feature_tokens = list(
        chain.from_iterable(
            user_features["feature_tokens"]
        )
    )

    all_item_feature_tokens = list(
        chain.from_iterable(
            item_features["feature_tokens"]
        )
    )

    dataset = Dataset()

    dataset.fit(
        users=hybrid_user_ids,
        items=hybrid_item_ids,
        user_features=all_user_feature_tokens,
        item_features=all_item_feature_tokens,
    )

    # 1. 사용자-상품 긍정 상호작용 행렬
    interactions, _ = dataset.build_interactions(
        (
            row.author_id,
            row.product_id,
            row.interaction,
        )
        for row in hybrid_interactions.itertuples()
    )

    # 2. 사용자 피부 특성 행렬
    user_feature_matrix = dataset.build_user_features(
        (
            row.author_id,
            row.feature_tokens,
        )
        for row in user_features.itertuples()
    )

    # 3. 상품 속성 행렬
    item_feature_matrix = dataset.build_item_features(
        (
            row.product_id,
            row.feature_tokens,
        )
        for row in item_features.itertuples()
    )

    print("상호작용 행렬:", interactions.shape)
    print("상호작용 수:", interactions.nnz)

    print("사용자 피처 행렬:", user_feature_matrix.shape)
    print("상품 피처 행렬:", item_feature_matrix.shape)
    return {"dataset": dataset, "interactions": interactions, "user_feature_matrix": user_feature_matrix, "item_feature_matrix": item_feature_matrix, "item_features": item_features, "n_train_users": len(hybrid_user_ids), "n_train_items": len(hybrid_item_ids)}

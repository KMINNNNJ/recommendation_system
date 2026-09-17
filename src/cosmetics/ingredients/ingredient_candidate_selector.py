import io
import logging
import os
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.cosmetics.ingredients.ingredient_extractor import (
    normalize_ingredient_key,
    parse_ingredients,
)


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")

if not S3_BUCKET:
    raise RuntimeError(
        f"S3_BUCKET이 .env에 없습니다: {ENV_PATH}"
    )

S3_DICTIONARY_KEY = (
    "processed/cosmetics/ingredient_dictionary_filtered.csv"
)
S3_PRODUCT_KEY = "raw/sephora/product_info.csv"
S3_OUTPUT_KEY = (
    "processed/cosmetics/ingredient_candidates.csv"
)

TOP_N = 100


def get_s3_client():
    session_kwargs = {}

    if AWS_PROFILE:
        session_kwargs["profile_name"] = AWS_PROFILE

    if AWS_REGION:
        session_kwargs["region_name"] = AWS_REGION

    return boto3.Session(
        **session_kwargs
    ).client("s3")


def load_csv_from_s3(key):
    s3 = get_s3_client()
    logger.info(
        "S3 read: s3://%s/%s",
        S3_BUCKET,
        key,
    )

    response = s3.get_object(
        Bucket=S3_BUCKET,
        Key=key,
    )

    return pd.read_csv(
        io.BytesIO(response["Body"].read()),
        low_memory=False,
    )


def save_to_s3(df, key):
    s3 = get_s3_client()

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buffer.getvalue().encode("utf-8-sig"),
        ContentType="text/csv",
    )

    logger.info(
        "S3 save: s3://%s/%s (%s rows)",
        S3_BUCKET,
        key,
        f"{len(df):,}",
    )


def load_dictionary():
    dictionary = load_csv_from_s3(
        S3_DICTIONARY_KEY
    )

    required_columns = {
        "ingredient_en",
        "regulate_type",
    }
    missing_columns = (
        required_columns
        - set(dictionary.columns)
    )

    if missing_columns:
        raise ValueError(
            "성분 사전에 필요한 컬럼이 없습니다: "
            f"{sorted(missing_columns)}"
        )

    return dictionary


def load_products():
    products = load_csv_from_s3(
        S3_PRODUCT_KEY
    )

    required_columns = {
        "product_id",
        "ingredients",
        "primary_category",
        "rating",
        "reviews",
        "loves_count",
        "price_usd",
    }
    missing_columns = (
        required_columns
        - set(products.columns)
    )

    if missing_columns:
        raise ValueError(
            "product_info.csv에 필요한 컬럼이 없습니다: "
            f"{sorted(missing_columns)}"
        )

    skincare = products[
        products["primary_category"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
        .eq("skincare")
    ].copy()

    skincare = skincare[
        skincare["ingredients"].notna()
    ].copy()

    return skincare


def get_allowed_ingredients(dictionary):
    allowed = dictionary.copy()

    allowed["ingredient_key"] = allowed[
        "ingredient_en"
    ].apply(normalize_ingredient_key)

    allowed = allowed[
        allowed["ingredient_key"].ne("")
    ].copy()

    duplicate_count = (
        allowed["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        duplicates = allowed[
            allowed["ingredient_key"].duplicated(
                keep=False
            )
        ].copy()

        preview_columns = [
            column
            for column in [
                "ingredient_key",
                "ingredient_en",
                "ingredient_kr",
                "regulate_type",
            ]
            if column in duplicates.columns
        ]

        logger.error(
            "Duplicate ingredient keys found: %s\n%s",
            duplicate_count,
            duplicates[
                preview_columns
            ]
            .sort_values("ingredient_key")
            .head(30)
            .to_string(index=False),
        )

        raise RuntimeError(
            "ingredient_dictionary_filtered.csv에 "
            "ingredient_key 중복이 존재합니다. "
            "앞 단계의 성분 사전 또는 규제 필터를 확인하세요."
        )

    regulate_type = (
        allowed["regulate_type"]
        .fillna("")
        .astype(str)
    )
    prohibited_mask = regulate_type.str.contains(
        "금지",
        regex=False,
    )

    logger.info(
        "Excluded prohibited ingredients: %s",
        f"{int(prohibited_mask.sum()):,}",
    )

    allowed = allowed[
        ~prohibited_mask
    ].copy()

    logger.info(
        "Allowed ingredients: %s",
        f"{len(allowed):,}",
    )

    return allowed


def build_product_ingredient_table(products):
    rows = []

    for _, product in products.iterrows():
        ingredients = parse_ingredients(
            product["ingredients"]
        )
        product_keys = set()

        for ingredient in ingredients:
            ingredient_key = normalize_ingredient_key(
                ingredient
            )

            if (
                not ingredient_key
                or ingredient_key in product_keys
            ):
                continue

            product_keys.add(ingredient_key)

            rows.append(
                {
                    "product_id": product["product_id"],
                    "ingredient_key": ingredient_key,
                    "rating": product["rating"],
                    "reviews": product["reviews"],
                    "loves_count": product["loves_count"],
                    "price_usd": product["price_usd"],
                }
            )

    return pd.DataFrame(rows)


def build_statistics(product_ingredients):
    data = product_ingredients.copy()

    numeric_columns = [
        "rating",
        "reviews",
        "loves_count",
        "price_usd",
    ]

    for column in numeric_columns:
        data[column] = pd.to_numeric(
            data[column],
            errors="coerce",
        )

    return (
        data.groupby(
            "ingredient_key",
            as_index=False,
        )
        .agg(
            product_count=(
                "product_id",
                "nunique",
            ),
            avg_rating=(
                "rating",
                "mean",
            ),
            total_reviews=(
                "reviews",
                "sum",
            ),
            avg_reviews=(
                "reviews",
                "mean",
            ),
            total_loves=(
                "loves_count",
                "sum",
            ),
            avg_loves=(
                "loves_count",
                "mean",
            ),
            avg_price=(
                "price_usd",
                "mean",
            ),
        )
    )


def minmax(series):
    values = series.fillna(0)
    min_value = values.min()
    max_value = values.max()

    if min_value == max_value:
        return pd.Series(
            0.0,
            index=values.index,
        )

    return (
        values - min_value
    ) / (
        max_value - min_value
    )


def calculate_product_score(df):
    result = df.copy()

    result["frequency_score"] = minmax(
        result["product_count"]
    )
    result["love_score"] = minmax(
        np.log1p(
            result["total_loves"].fillna(0)
        )
    )
    result["review_score"] = minmax(
        np.log1p(
            result["total_reviews"].fillna(0)
        )
    )
    result["rating_score"] = (
        result["avg_rating"].fillna(0)
        / 5
    )

    result["product_score"] = (
        result["frequency_score"] * 0.40
        + result["love_score"] * 0.30
        + result["review_score"] * 0.20
        + result["rating_score"] * 0.10
    ).round(4)

    return result


def select_candidates(
    dictionary,
    statistics,
):
    allowed = get_allowed_ingredients(
        dictionary
    )

    allowed = allowed.drop(
        columns=[
            column
            for column in [
                "product_count",
                "product_ratio",
            ]
            if column in allowed.columns
        ],
        errors="ignore",
    )

    data = allowed.merge(
        statistics,
        on="ingredient_key",
        how="left",
    )

    data = data[
        data["product_count"].notna()
    ].copy()

    logger.info(
        "Allowed ingredients linked to Sephora products: %s",
        f"{len(data):,}",
    )

    data = calculate_product_score(data)

    candidates = (
        data.sort_values(
            by=[
                "product_score",
                "product_count",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .head(TOP_N)
        .reset_index(drop=True)
    )

    candidates.insert(
        0,
        "candidate_rank",
        range(1, len(candidates) + 1),
    )

    duplicate_count = (
        candidates["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "최종 후보에 ingredient_key 중복이 발생했습니다."
        )

    columns = [
        "candidate_rank",
        "ingredient_key",
        "ingredient_en",
        "ingredient_kr",
        "product_count",
        "avg_rating",
        "total_reviews",
        "avg_reviews",
        "total_loves",
        "avg_loves",
        "avg_price",
        "frequency_score",
        "love_score",
        "review_score",
        "rating_score",
        "product_score",
        "regulate_type",
        "limit_condition",
    ]

    existing_columns = [
        column
        for column in columns
        if column in candidates.columns
    ]

    return candidates[
        existing_columns
    ]


def save_result(df):
    save_to_s3(
        df,
        S3_OUTPUT_KEY,
    )


def main():
    dictionary = load_dictionary()
    products = load_products()

    logger.info(
        "Filtered ingredient dictionary: %s rows",
        f"{len(dictionary):,}",
    )
    logger.info(
        "Skincare products with ingredients: %s",
        f"{len(products):,}",
    )

    product_ingredients = (
        build_product_ingredient_table(
            products
        )
    )

    logger.info(
        "Product-ingredient pairs: %s",
        f"{len(product_ingredients):,}",
    )

    statistics = build_statistics(
        product_ingredients
    )

    logger.info(
        "Ingredients with product statistics: %s",
        f"{len(statistics):,}",
    )

    candidates = select_candidates(
        dictionary,
        statistics,
    )

    preview_columns = [
        column
        for column in [
            "candidate_rank",
            "ingredient_en",
            "ingredient_kr",
            "product_count",
            "avg_rating",
            "total_reviews",
            "total_loves",
            "product_score",
            "regulate_type",
        ]
        if column in candidates.columns
    ]

    logger.info(
        "Selected candidates: %s\n%s",
        f"{len(candidates):,}",
        candidates[
            preview_columns
        ]
        .head(30)
        .to_string(index=False),
    )

    save_result(candidates)


if __name__ == "__main__":
    main()

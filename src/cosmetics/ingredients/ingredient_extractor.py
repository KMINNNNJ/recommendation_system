import ast
import io
import logging
import os
import re
from collections import Counter
from pathlib import Path

import boto3
import pandas as pd
from dotenv import load_dotenv


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")

S3_INPUT_KEY = "raw/sephora/product_info.csv"
S3_OUTPUT_KEY = "processed/cosmetics/all_ingredients.csv"

MAX_INGREDIENT_KEY_LENGTH = 255

if not S3_BUCKET:
    raise RuntimeError(
        f"S3_BUCKET이 .env에 없습니다: {ENV_PATH}"
    )


def get_s3_client():
    session_kwargs = {}

    if AWS_PROFILE:
        session_kwargs["profile_name"] = AWS_PROFILE

    if AWS_REGION:
        session_kwargs["region_name"] = AWS_REGION

    return boto3.Session(
        **session_kwargs
    ).client("s3")


def load_product_data():
    s3 = get_s3_client()

    logger.info(
        "S3 read: s3://%s/%s",
        S3_BUCKET,
        S3_INPUT_KEY,
    )

    response = s3.get_object(
        Bucket=S3_BUCKET,
        Key=S3_INPUT_KEY,
    )

    return pd.read_csv(
        io.BytesIO(response["Body"].read()),
        low_memory=False,
    )


def filter_skincare(products):
    required_columns = {
        "primary_category",
        "ingredients",
    }
    missing_columns = (
        required_columns - set(products.columns)
    )

    if missing_columns:
        raise ValueError(
            "상품 데이터에 필요한 컬럼이 없습니다: "
            f"{sorted(missing_columns)}"
        )

    skincare_mask = (
        products["primary_category"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
        .eq("skincare")
    )

    return products.loc[
        skincare_mask
        & products["ingredients"].notna()
    ].copy()


def clean_ingredient_name(name):
    text = str(name).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip("[]{}\"' \t\r\n")
    text = text.rstrip(".,;").strip()

    return text


def normalize_ingredient_key(name):
    name = clean_ingredient_name(name)

    if not name:
        return ""

    return re.sub(
        r"\s+",
        "",
        name.casefold(),
    )


def parse_ingredients(value):
    if pd.isna(value):
        return []

    text = str(value).strip()

    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            # 원본 성분명에 포함된 역슬래시가 literal_eval에서
            # escape 문자로 해석되지 않도록 보호한다.
            safe_text = text.replace("\\", "\\\\")
            parsed = ast.literal_eval(safe_text)

            if isinstance(parsed, list):
                items = [
                    str(item)
                    for item in parsed
                    if item is not None
                ]
            else:
                items = [str(parsed)]

        except (ValueError, SyntaxError):
            items = [text]

    else:
        items = [text]

    ingredients = []

    for item in items:
        item = item.strip()

        if not item or item.endswith(":"):
            continue

        # 1,2-Hexanediol처럼 숫자 사이의 쉼표는 분리하지 않는다.
        protected = re.sub(
            r"(?<=\d),(?=\s*\d)",
            "<NUM_COMMA>",
            item,
        )

        for part in re.split(r"[,;\n]+", protected):
            ingredient = clean_ingredient_name(
                part.replace("<NUM_COMMA>", ",")
            )

            if not ingredient:
                continue

            if re.fullmatch(r"\d+", ingredient):
                continue

            key = normalize_ingredient_key(
                ingredient
            )

            if not key:
                continue

            if len(key) > MAX_INGREDIENT_KEY_LENGTH:
                logger.warning(
                    "Skipped unusually long ingredient: "
                    "key_length=%s, value=%s",
                    len(key),
                    ingredient[:150],
                )
                continue

            ingredients.append(ingredient)

    unique_ingredients = {}

    for ingredient in ingredients:
        key = normalize_ingredient_key(
            ingredient
        )

        if key and key not in unique_ingredients:
            unique_ingredients[key] = ingredient

    return list(unique_ingredients.values())


def build_ingredient_statistics(products):
    counter = Counter()
    display_names = {}
    variants = {}

    for value in products["ingredients"]:
        product_keys = set()

        for ingredient in parse_ingredients(value):
            key = normalize_ingredient_key(
                ingredient
            )

            if not key or key in product_keys:
                continue

            product_keys.add(key)

            if key not in display_names:
                display_names[key] = ingredient

            variants.setdefault(
                key,
                set(),
            ).add(ingredient)

            counter[key] += 1

    columns = [
        "ingredient_key",
        "ingredient_en",
        "product_count",
        "product_ratio",
        "variant_count",
    ]

    if not counter:
        return pd.DataFrame(columns=columns)

    total_products = len(products)

    rows = [
        {
            "ingredient_key": key,
            "ingredient_en": display_names[key],
            "product_count": product_count,
            "product_ratio": round(
                product_count / total_products,
                4,
            ),
            "variant_count": len(
                variants[key]
            ),
        }
        for key, product_count in counter.items()
    ]

    return (
        pd.DataFrame(rows)
        .sort_values(
            by=[
                "product_count",
                "ingredient_en",
            ],
            ascending=[
                False,
                True,
            ],
        )
        .reset_index(drop=True)
    )


def log_variant_summary(df):
    duplicated = df[
        df["variant_count"] > 1
    ].copy()

    logger.info(
        "Ingredients with name variants: %s",
        f"{len(duplicated):,}",
    )

    if duplicated.empty:
        return

    logger.info(
        "Variant sample:\n%s",
        duplicated[
            [
                "ingredient_en",
                "variant_count",
                "product_count",
            ]
        ]
        .head(30)
        .to_string(index=False),
    )


def validate_ingredient_keys(df):
    duplicate_count = (
        df["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count == 0:
        logger.info(
            "ingredient_key duplicates: 0"
        )
        return

    duplicates = (
        df[
            df["ingredient_key"].duplicated(
                keep=False
            )
        ]
        .sort_values("ingredient_key")
        .head(30)
    )

    logger.error(
        "Duplicate ingredient keys found: %s\n%s",
        duplicate_count,
        duplicates.to_string(index=False),
    )

    raise RuntimeError(
        "all_ingredients.csv에 ingredient_key 중복이 있습니다."
    )


def save_to_s3(df):
    s3 = get_s3_client()

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=S3_OUTPUT_KEY,
        Body=buffer.getvalue().encode("utf-8-sig"),
        ContentType="text/csv",
    )

    logger.info(
        "S3 save: s3://%s/%s (%s rows)",
        S3_BUCKET,
        S3_OUTPUT_KEY,
        f"{len(df):,}",
    )


def main():
    products = load_product_data()
    skincare = filter_skincare(
        products
    )

    logger.info(
        "Products: total=%s, skincare_with_ingredients=%s",
        f"{len(products):,}",
        f"{len(skincare):,}",
    )

    ingredient_stats = (
        build_ingredient_statistics(
            skincare
        )
    )

    logger.info(
        "Unique normalized ingredients: %s",
        f"{len(ingredient_stats):,}",
    )
    logger.info(
        "Top ingredients:\n%s",
        ingredient_stats
        .head(30)
        .to_string(index=False),
    )

    log_variant_summary(
        ingredient_stats
    )
    validate_ingredient_keys(
        ingredient_stats
    )
    save_to_s3(
        ingredient_stats
    )


if __name__ == "__main__":
    main()

import io
import logging
import os
from pathlib import Path

import boto3
import pandas as pd
import pymysql
from dotenv import load_dotenv

from src.cosmetics.ingredients.ingredient_extractor import (
    normalize_ingredient_key,
    parse_ingredients,
)


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

S3_PRODUCT_KEY = "raw/sephora/product_info.csv"
BATCH_SIZE = 5000


def get_s3_client():
    session_kwargs = {}

    if AWS_PROFILE:
        session_kwargs["profile_name"] = AWS_PROFILE

    if AWS_REGION:
        session_kwargs["region_name"] = AWS_REGION

    return boto3.Session(
        **session_kwargs
    ).client("s3")


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
    )


def load_products_from_s3():
    if not S3_BUCKET:
        raise RuntimeError(
            f"S3_BUCKET이 .env에 없습니다: {ENV_PATH}"
        )

    s3 = get_s3_client()

    logger.info(
        "S3 read: s3://%s/%s",
        S3_BUCKET,
        S3_PRODUCT_KEY,
    )

    response = s3.get_object(
        Bucket=S3_BUCKET,
        Key=S3_PRODUCT_KEY,
    )

    products = pd.read_csv(
        io.BytesIO(
            response["Body"].read()
        ),
        low_memory=False,
    )

    required_columns = {
        "product_id",
        "primary_category",
        "ingredients",
    }
    missing_columns = (
        required_columns
        - set(products.columns)
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

    skincare = products.loc[
        skincare_mask
        & products["ingredients"].notna()
    ].copy()

    logger.info(
        "Products loaded: total=%s, skincare_with_ingredients=%s",
        f"{len(products):,}",
        f"{len(skincare):,}",
    )

    return skincare


def load_valid_ingredient_keys(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT ingredient_key
            FROM ingredients
            """
        )
        rows = cursor.fetchall()

    ingredient_keys = {
        str(row[0]).strip()
        for row in rows
        if row[0] is not None
        and str(row[0]).strip()
    }

    logger.info(
        "Registered ingredient keys: %s",
        f"{len(ingredient_keys):,}",
    )

    return ingredient_keys


def build_product_ingredients(
    products,
    valid_ingredient_keys,
):
    rows = set()
    missing_keys = set()

    for _, product in products.iterrows():
        product_id = str(
            product["product_id"]
        ).strip()

        if not product_id:
            continue

        ingredients = parse_ingredients(
            product["ingredients"]
        )

        for ingredient in ingredients:
            ingredient_key = (
                normalize_ingredient_key(
                    ingredient
                )
            )

            if not ingredient_key:
                continue

            if (
                ingredient_key
                not in valid_ingredient_keys
            ):
                missing_keys.add(
                    ingredient_key
                )
                continue

            rows.add(
                (
                    product_id,
                    ingredient_key,
                )
            )

    rows = sorted(rows)

    logger.info(
        "Product-ingredient pairs: %s",
        f"{len(rows):,}",
    )
    logger.info(
        "Skipped ingredient keys not found in DB: %s",
        f"{len(missing_keys):,}",
    )

    if missing_keys:
        logger.info(
            "Missing key sample: %s",
            ", ".join(
                sorted(missing_keys)[:10]
            ),
        )

    return rows


def save_product_ingredients(
    conn,
    rows,
):
    sql = """
        INSERT INTO product_ingredients (
            product_id,
            ingredient_key
        )
        VALUES (%s, %s)
    """

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM product_ingredients"
            )

            for start in range(
                0,
                len(rows),
                BATCH_SIZE,
            ):
                batch = rows[
                    start:start + BATCH_SIZE
                ]

                cursor.executemany(
                    sql,
                    batch,
                )

                logger.info(
                    "Loading product_ingredients: %s/%s",
                    f"{min(start + BATCH_SIZE, len(rows)):,}",
                    f"{len(rows):,}",
                )

        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM product_ingredients
                """
            )
            count = cursor.fetchone()[0]

        logger.info(
            "MariaDB product_ingredients load complete: %s rows",
            f"{count:,}",
        )

        return count

    except Exception:
        conn.rollback()
        raise


def main():
    products = load_products_from_s3()
    conn = get_db_connection()

    try:
        valid_ingredient_keys = (
            load_valid_ingredient_keys(
                conn
            )
        )

        rows = build_product_ingredients(
            products,
            valid_ingredient_keys,
        )

        save_product_ingredients(
            conn,
            rows,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()

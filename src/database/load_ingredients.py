import io
import logging
import os
from pathlib import Path

import boto3
import pandas as pd
import pymysql
from dotenv import load_dotenv


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

S3_INGREDIENT_KEY = ("processed/cosmetics/ingredient_dictionary_filtered.csv")

INGREDIENT_COLUMNS = [
    "ingredient_key",
    "ingredient_en",
    "ingredient_kr",
    "cas_no",
    "origin",
    "synonym",
    "regulate_type",
    "limit_condition",
    "matched",
    "recommendable",
    "needs_review",
]

BOOLEAN_COLUMN_INDEXES = (
    8,
    9,
    10,
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


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
    )


def load_ingredients_from_s3():
    if not S3_BUCKET:
        raise RuntimeError(
            f"S3_BUCKET이 .env에 없습니다: {ENV_PATH}"
        )

    s3 = get_s3_client()

    logger.info(
        "S3 read: s3://%s/%s",
        S3_BUCKET,
        S3_INGREDIENT_KEY,
    )

    response = s3.get_object(
        Bucket=S3_BUCKET,
        Key=S3_INGREDIENT_KEY,
    )

    ingredients = pd.read_csv(
        io.BytesIO(
            response["Body"].read()
        ),
        low_memory=False,
    )

    missing_columns = [
        column
        for column in INGREDIENT_COLUMNS
        if column not in ingredients.columns
    ]

    if missing_columns:
        raise ValueError(
            "필요한 컬럼이 없습니다: "
            f"{missing_columns}"
        )

    ingredients = ingredients[
        INGREDIENT_COLUMNS
    ].copy()

    logger.info(
        "Loaded ingredients from S3: %s",
        f"{len(ingredients):,}",
    )

    return ingredients


def clean_value(value):
    if pd.isna(value):
        return None

    return value


def clean_boolean(value):
    if pd.isna(value):
        return None

    if isinstance(value, bool):
        return int(value)

    text = str(
        value
    ).strip().casefold()

    if text in {
        "true",
        "1",
    }:
        return 1

    if text in {
        "false",
        "0",
    }:
        return 0

    return None


def build_rows(ingredients):
    rows = []

    for values in ingredients.itertuples(
        index=False,
        name=None,
    ):
        row = list(values)

        for index in BOOLEAN_COLUMN_INDEXES:
            row[index] = clean_boolean(
                row[index]
            )

        rows.append(
            tuple(
                clean_value(value)
                for value in row
            )
        )

    return rows


def load_ingredients_to_mariadb(ingredients):
    rows = build_rows(
        ingredients
    )

    if not rows:
        logger.info(
            "No ingredient rows to load."
        )
        return 0

    sql = """
        INSERT INTO ingredients (
            ingredient_key,
            ingredient_en,
            ingredient_kr,
            cas_no,
            origin,
            synonym,
            regulate_type,
            limit_condition,
            matched,
            recommendable,
            needs_review
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            ingredient_en = VALUES(ingredient_en),
            ingredient_kr = VALUES(ingredient_kr),
            cas_no = VALUES(cas_no),
            origin = VALUES(origin),
            synonym = VALUES(synonym),
            regulate_type = VALUES(regulate_type),
            limit_condition = VALUES(limit_condition),
            matched = VALUES(matched),
            recommendable = VALUES(recommendable),
            needs_review = VALUES(needs_review)
    """

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                sql,
                rows,
            )

        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM ingredients"
            )
            count = cursor.fetchone()[0]

        logger.info(
            "MariaDB ingredients load complete: %s rows",
            f"{count:,}",
        )

        return count

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def main():
    ingredients = (
        load_ingredients_from_s3()
    )

    load_ingredients_to_mariadb(
        ingredients
    )


if __name__ == "__main__":
    main()

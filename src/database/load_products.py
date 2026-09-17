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
DB_PORT = int(os.getenv("DB_PORT", "3306",))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

S3_PRODUCT_KEY = "raw/sephora/product_info.csv"
S3_REVIEW_KEY = "raw/sephora/reviews_all.csv"

PRODUCT_COLUMNS = [
    "product_id",
    "product_name",
    "brand_name",
    "price_usd",
    "rating",
    "reviews",
    "loves_count",
]

NUMERIC_COLUMNS = [
    "price_usd",
    "rating",
    "reviews",
    "loves_count",
]


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

    missing_columns = [
        column
        for column in PRODUCT_COLUMNS
        if column not in products.columns
    ]

    if missing_columns:
        raise ValueError(
            "상품 데이터에 필요한 컬럼이 없습니다: "
            f"{missing_columns}"
        )

    products = products[
        PRODUCT_COLUMNS
    ].copy()

    products["product_id"] = (
        products["product_id"]
        .astype(str)
        .str.strip()
    )

    for column in NUMERIC_COLUMNS:
        products[column] = pd.to_numeric(
            products[column],
            errors="coerce",
        )

    logger.info(
        "Loaded products from S3: %s",
        f"{len(products):,}",
    )

    return products


def load_latest_review_dates_from_s3():
    if not S3_BUCKET:
        raise RuntimeError(
            f"S3_BUCKET이 .env에 없습니다: {ENV_PATH}"
        )

    s3 = get_s3_client()

    logger.info(
        "S3 read: s3://%s/%s",
        S3_BUCKET,
        S3_REVIEW_KEY,
    )

    response = s3.get_object(
        Bucket=S3_BUCKET,
        Key=S3_REVIEW_KEY,
    )

    reviews = pd.read_csv(
        io.BytesIO(
            response["Body"].read()
        ),
        usecols=[
            "product_id",
            "submission_time",
        ],
        low_memory=False,
    )

    reviews["product_id"] = (
        reviews["product_id"]
        .astype(str)
        .str.strip()
    )

    reviews["submission_time"] = pd.to_datetime(
        reviews["submission_time"],
        errors="coerce",
    )

    reviews = reviews.dropna(
        subset=[
            "product_id",
            "submission_time",
        ]
    )

    latest_review_dates = (
        reviews.groupby(
            "product_id",
            as_index=False,
        )["submission_time"]
        .max()
        .rename(
            columns={
                "submission_time": "latest_review_date",
            }
        )
    )

    latest_review_dates[
        "latest_review_date"
    ] = (
        latest_review_dates[
            "latest_review_date"
        ]
        .dt.date
    )

    logger.info(
        "Products with latest review date: %s",
        f"{len(latest_review_dates):,}",
    )

    if not latest_review_dates.empty:
        logger.info(
            "Latest review date in dataset: %s",
            latest_review_dates[
                "latest_review_date"
            ].max(),
        )

    return latest_review_dates


def merge_product_review_dates(
    products,
    latest_review_dates,
):
    merged = products.merge(
        latest_review_dates,
        on="product_id",
        how="left",
        validate="one_to_one",
    )

    matched_count = (
        merged["latest_review_date"]
        .notna()
        .sum()
    )

    logger.info(
        "Latest review date matched: %s/%s",
        f"{matched_count:,}",
        f"{len(merged):,}",
    )

    return merged


def clean_value(value):
    if pd.isna(value):
        return None

    return value


def ensure_latest_review_date_column(
    cursor,
):
    cursor.execute(
        """
        SHOW COLUMNS
        FROM products
        LIKE 'latest_review_date'
        """
    )

    if cursor.fetchone() is not None:
        return

    cursor.execute(
        """
        ALTER TABLE products
        ADD COLUMN latest_review_date DATE NULL
        """
    )

    logger.info(
        "Created products.latest_review_date column."
    )


def build_product_rows(products):
    columns = [
        "product_id",
        "product_name",
        "brand_name",
        "price_usd",
        "rating",
        "reviews",
        "loves_count",
        "latest_review_date",
    ]

    return [
        tuple(
            clean_value(value)
            for value in row
        )
        for row in products[
            columns
        ].itertuples(
            index=False,
            name=None,
        )
    ]


def load_products_to_mariadb(products):
    rows = build_product_rows(
        products
    )

    if not rows:
        logger.info(
            "No product rows to load."
        )
        return {
            "total_count": 0,
            "dated_count": 0,
        }

    sql = """
        INSERT INTO products (
            product_id,
            product_name,
            brand_name,
            price_usd,
            rating,
            reviews,
            loves_count,
            latest_review_date
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            product_name = VALUES(product_name),
            brand_name = VALUES(brand_name),
            price_usd = VALUES(price_usd),
            rating = VALUES(rating),
            reviews = VALUES(reviews),
            loves_count = VALUES(loves_count),
            latest_review_date = VALUES(latest_review_date)
    """

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            ensure_latest_review_date_column(
                cursor
            )

            cursor.executemany(
                sql,
                rows,
            )

        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(
                        latest_review_date IS NOT NULL
                    ) AS dated_count
                FROM products
                """
            )

            total_count, dated_count = (
                cursor.fetchone()
            )

        total_count = int(
            total_count or 0
        )
        dated_count = int(
            dated_count or 0
        )

        logger.info(
            "MariaDB products load complete: %s rows",
            f"{total_count:,}",
        )
        logger.info(
            "Products with latest review date: %s",
            f"{dated_count:,}",
        )

        return {
            "total_count": total_count,
            "dated_count": dated_count,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def main():
    products = load_products_from_s3()

    latest_review_dates = (
        load_latest_review_dates_from_s3()
    )

    products = merge_product_review_dates(
        products=products,
        latest_review_dates=latest_review_dates,
    )

    load_products_to_mariadb(
        products
    )


if __name__ == "__main__":
    main()

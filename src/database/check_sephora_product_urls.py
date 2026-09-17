import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pymysql
import requests
from dotenv import load_dotenv


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

SITEMAP_URL = "https://www.sephora.com/sitemaps/products-sitemap.xml"

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def load_skincare_product_ids():
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT p.product_id
                FROM products p
                INNER JOIN product_ingredients pi
                    ON p.product_id = pi.product_id
                """
            )
            rows = cursor.fetchall()

        return {
            str(row["product_id"]).strip()
            for row in rows
        }

    finally:
        conn.close()


def read_product_sitemap():
    logger.info(
        "Reading Sephora sitemap: %s",
        SITEMAP_URL,
    )

    response = requests.get(
        SITEMAP_URL,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )
    response.raise_for_status()

    root = ET.fromstring(
        response.content
    )

    urls = []

    for element in root.iter():
        if (
            element.tag.endswith("loc")
            and element.text
        ):
            url = element.text.strip()

            if "/product/" in url:
                urls.append(url)

    return urls


def extract_product_id(url):
    match = re.search(
        r"(P\d+)(?:$|[/?#])",
        url,
        re.IGNORECASE,
    )

    if match is None:
        return None

    return match.group(1).upper()


def build_product_url_map(urls):
    product_urls = {}

    for url in urls:
        product_id = extract_product_id(
            url
        )

        if product_id:
            product_urls[product_id] = url

    return product_urls


def update_product_urls(
    product_urls,
    matched_ids,
):
    rows = [
        (
            product_urls[product_id],
            product_id,
        )
        for product_id in matched_ids
    ]

    if not rows:
        logger.info(
            "No product URLs to update."
        )
        return 0

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE products
                SET product_url = %s
                WHERE product_id = %s
                """,
                rows,
            )

        conn.commit()
        return len(rows)

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def count_saved_urls():
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS url_count
                FROM products
                WHERE product_url IS NOT NULL
                  AND product_url <> ''
                """
            )
            row = cursor.fetchone()

        return row["url_count"]

    finally:
        conn.close()


def load_saved_url_samples(limit=10):
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    product_id,
                    product_name,
                    product_url
                FROM products
                WHERE product_url IS NOT NULL
                  AND product_url <> ''
                ORDER BY product_id
                LIMIT %s
                """,
                (int(limit),),
            )
            return cursor.fetchall()

    finally:
        conn.close()


def print_match_samples(
    matched_ids,
    product_urls,
    limit=20,
):
    print("\n[매칭 예시]")

    for product_id in sorted(
        matched_ids
    )[:limit]:
        print(
            f"{product_id} -> "
            f"{product_urls[product_id]}"
        )


def print_saved_samples(rows):
    print("\n[DB 저장 예시]")

    for row in rows:
        print(
            f"{row['product_id']} | "
            f"{row['product_name']}"
        )
        print(row["product_url"])
        print()


def main():
    db_product_ids = (
        load_skincare_product_ids()
    )

    print(
        "스킨케어 후보 상품 수:",
        len(db_product_ids),
    )

    sitemap_urls = (
        read_product_sitemap()
    )
    product_urls = (
        build_product_url_map(
            sitemap_urls
        )
    )

    print(
        "Sephora 상품 URL 수:",
        len(product_urls),
    )

    matched_ids = (
        db_product_ids
        & product_urls.keys()
    )

    match_rate = (
        len(matched_ids)
        / len(db_product_ids)
        * 100
        if db_product_ids
        else 0
    )

    print(
        "스킨케어 상품 매칭 수:",
        len(matched_ids),
    )
    print(
        f"스킨케어 매칭률: "
        f"{match_rate:.2f}%"
    )

    print_match_samples(
        matched_ids,
        product_urls,
    )

    updated_count = update_product_urls(
        product_urls,
        matched_ids,
    )

    print(
        "\n상품 URL 저장 완료:",
        updated_count,
    )
    print(
        "DB에 저장된 product_url 수:",
        count_saved_urls(),
    )

    samples = load_saved_url_samples()
    print_saved_samples(samples)


if __name__ == "__main__":
    main()

import io
import logging
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

import boto3
import pandas as pd
import requests
from dotenv import load_dotenv


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")

S3_INPUT_KEY = "processed/cosmetics/all_ingredients.csv"
S3_OUTPUT_KEY = "processed/cosmetics/ingredient_dictionary.csv"
S3_UNMATCHED_KEY = "processed/cosmetics/ingredient_unmatched.csv"

INGREDIENT_API_KEY = unquote(
    os.getenv("INGREDIENT_API_KEY")
    or os.getenv("ingredient_api_key", "")
)

MFDS_API_URL = (
    "https://apis.data.go.kr/1471000/"
    "CsmtcsIngdCpntInfoService01/"
    "getCsmtcsIngdCpntInfoService01"
)
PAGE_SIZE = 100

if not INGREDIENT_API_KEY:
    raise RuntimeError(
        f"INGREDIENT_API_KEY가 .env에 없습니다: {ENV_PATH}"
    )

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


def load_ingredients():
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

    df = pd.read_csv(
        io.BytesIO(response["Body"].read()),
        low_memory=False,
    )

    required_columns = {
        "ingredient_key",
        "ingredient_en",
        "product_count",
        "product_ratio",
    }
    missing_columns = (
        required_columns - set(df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"필수 컬럼이 없습니다: {sorted(missing_columns)}"
        )

    duplicate_count = (
        df["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "all_ingredients.csv에 ingredient_key 중복이 있습니다."
        )

    logger.info(
        "Loaded Sephora ingredients: %s",
        f"{len(df):,}",
    )

    return df


def normalize_name(value):
    if pd.isna(value):
        return ""

    return re.sub(
        r"\s+",
        "",
        str(value).strip().casefold(),
    )


def request_page(
    page_no,
    max_retries=5,
):
    params = {
        "serviceKey": INGREDIENT_API_KEY,
        "pageNo": page_no,
        "numOfRows": PAGE_SIZE,
        "type": "json",
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                MFDS_API_URL,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            header = data.get("header", {})

            if header.get("resultCode") != "00":
                raise RuntimeError(
                    f"식약처 API 요청 실패: {header}"
                )

            return data

        except requests.exceptions.RequestException as error:
            if attempt == max_retries:
                raise

            wait_time = attempt * 2

            logger.warning(
                "MFDS request failed: page=%s, attempt=%s/%s, "
                "retry_in=%ss, error=%s",
                page_no,
                attempt,
                max_retries,
                wait_time,
                error,
            )

            time.sleep(wait_time)

    raise RuntimeError(
        f"식약처 API 페이지 {page_no} 요청에 실패했습니다."
    )


def collect_mfds_ingredients():
    first_page = request_page(1)
    body = first_page.get("body", {})

    if "totalCount" not in body:
        raise RuntimeError(
            f"totalCount가 없습니다: {body}"
        )

    total_count = int(body["totalCount"])
    total_pages = math.ceil(
        total_count / PAGE_SIZE
    )

    logger.info(
        "MFDS ingredient collection: total=%s, pages=%s",
        f"{total_count:,}",
        f"{total_pages:,}",
    )

    rows = []

    for page_no in range(1, total_pages + 1):
        if (
            page_no == 1
            or page_no == total_pages
            or page_no % 20 == 0
        ):
            logger.info(
                "MFDS collection progress: %s/%s",
                page_no,
                total_pages,
            )

        data = (
            first_page
            if page_no == 1
            else request_page(page_no)
        )

        items = (
            data.get("body", {})
            .get("items", [])
        )

        if isinstance(items, list):
            rows.extend(items)
        elif isinstance(items, dict):
            rows.append(items)

    result = pd.DataFrame(rows)

    logger.info(
        "MFDS raw ingredients collected: %s",
        f"{len(result):,}",
    )

    return result


def clean_mfds_dictionary(df):
    data = df.rename(
        columns={
            "INGR_KOR_NAME": "ingredient_kr",
            "INGR_ENG_NAME": "mfds_ingredient_en",
            "CAS_NO": "cas_no",
            "ORIGIN_MAJOR_KOR_NAME": "origin",
            "INGR_SYNONYM": "synonym",
        }
    ).copy()

    columns = [
        "ingredient_kr",
        "mfds_ingredient_en",
        "cas_no",
        "origin",
        "synonym",
    ]

    for column in columns:
        if column not in data.columns:
            data[column] = ""

        data[column] = (
            data[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    data = data[columns].copy()
    data["mfds_key"] = data[
        "mfds_ingredient_en"
    ].apply(normalize_name)

    data = data[
        data["mfds_key"].ne("")
    ].copy()

    duplicate_mask = data[
        "mfds_key"
    ].duplicated(keep=False)

    duplicate_rows = data[
        duplicate_mask
    ].copy()

    logger.info(
        "MFDS ingredients with English names: %s",
        f"{len(data):,}",
    )
    logger.info(
        "MFDS duplicate rows=%s, duplicate_keys=%s",
        f"{len(duplicate_rows):,}",
        f"{duplicate_rows['mfds_key'].nunique():,}",
    )

    if not duplicate_rows.empty:
        logger.info(
            "MFDS duplicate sample:\n%s",
            duplicate_rows[
                [
                    "mfds_key",
                    "mfds_ingredient_en",
                    "ingredient_kr",
                    "cas_no",
                ]
            ]
            .head(30)
            .to_string(index=False),
        )

    data = data.drop_duplicates(
        subset=[
            "mfds_key",
            "ingredient_kr",
            "cas_no",
        ]
    ).copy()

    key_counts = (
        data.groupby("mfds_key")
        .size()
    )

    ambiguous_keys = set(
        key_counts[
            key_counts > 1
        ].index
    )

    if ambiguous_keys:
        logger.info(
            "Excluded ambiguous MFDS keys: %s",
            f"{len(ambiguous_keys):,}",
        )

        data = data[
            ~data["mfds_key"].isin(
                ambiguous_keys
            )
        ].copy()

    duplicate_count = (
        data["mfds_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "자동 매칭용 식약처 데이터에 "
            "mfds_key 중복이 남아 있습니다."
        )

    logger.info(
        "MFDS keys available for exact matching: %s",
        f"{len(data):,}",
    )

    return data.reset_index(drop=True)


def build_dictionary(
    ingredients,
    mfds,
):
    source = ingredients.copy()
    source["match_key"] = (
        source["ingredient_key"]
        .astype(str)
        .str.strip()
    )

    mfds_lookup = mfds.copy()
    mfds_lookup["match_key"] = (
        mfds_lookup["mfds_key"]
    )

    result = source.merge(
        mfds_lookup[
            [
                "match_key",
                "ingredient_kr",
                "mfds_ingredient_en",
                "cas_no",
                "origin",
                "synonym",
            ]
        ],
        on="match_key",
        how="left",
    )

    text_columns = [
        "ingredient_kr",
        "mfds_ingredient_en",
        "cas_no",
        "origin",
        "synonym",
    ]
    result[text_columns] = (
        result[text_columns]
        .fillna("")
    )

    result["matched"] = result[
        "ingredient_kr"
    ].ne("")

    result = result.drop(
        columns=["match_key"]
    )

    duplicate_count = (
        result["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "ingredient_dictionary 생성 후 "
            "ingredient_key 중복이 발생했습니다."
        )

    columns = [
        "ingredient_key",
        "ingredient_en",
        "ingredient_kr",
        "product_count",
        "product_ratio",
        "variant_count",
        "cas_no",
        "origin",
        "synonym",
        "matched",
    ]

    existing_columns = [
        column
        for column in columns
        if column in result.columns
    ]

    return result[
        existing_columns
    ]


def save_to_s3(
    df,
    key,
):
    s3 = get_s3_client()

    buffer = io.StringIO()
    df.to_csv(
        buffer,
        index=False,
    )

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buffer.getvalue().encode(
            "utf-8-sig"
        ),
        ContentType="text/csv",
    )

    logger.info(
        "S3 save: s3://%s/%s (%s rows)",
        S3_BUCKET,
        key,
        f"{len(df):,}",
    )


def save_result(df):
    save_to_s3(
        df,
        S3_OUTPUT_KEY,
    )

    unmatched = df[
        ~df["matched"]
    ].copy()

    save_to_s3(
        unmatched,
        S3_UNMATCHED_KEY,
    )


def main():
    ingredients = load_ingredients()

    mfds_raw = collect_mfds_ingredients()
    mfds = clean_mfds_dictionary(
        mfds_raw
    )

    dictionary = build_dictionary(
        ingredients,
        mfds,
    )

    matched_count = int(
        dictionary["matched"].sum()
    )
    unmatched_count = (
        len(dictionary) - matched_count
    )
    match_rate = (
        matched_count
        / len(dictionary)
        * 100
        if len(dictionary)
        else 0
    )

    logger.info(
        "Ingredient matching: total=%s, matched=%s, "
        "unmatched=%s, match_rate=%.2f%%",
        f"{len(dictionary):,}",
        f"{matched_count:,}",
        f"{unmatched_count:,}",
        match_rate,
    )

    logger.info(
        "Dictionary sample:\n%s",
        dictionary[
            [
                "ingredient_key",
                "ingredient_en",
                "ingredient_kr",
                "matched",
            ]
        ]
        .head(30)
        .to_string(index=False),
    )

    save_result(
        dictionary
    )


if __name__ == "__main__":
    main()

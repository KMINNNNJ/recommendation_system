import io
import logging
import math
import os
import time
from pathlib import Path

import boto3
import pandas as pd
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from src.cosmetics.ingredients.ingredient_extractor import (
    normalize_ingredient_key,
)


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")

INGREDIENT_API_KEY = (
    os.getenv("INGREDIENT_API_KEY")
    or os.getenv("ingredient_api_key")
)

S3_DICTIONARY_KEY = ("processed/cosmetics/ingredient_dictionary.csv")
S3_RESTRICTION_RAW_KEY = ("processed/cosmetics/mfds_restricted_ingredients.csv")
S3_OUTPUT_KEY = ("processed/cosmetics/ingredient_dictionary_filtered.csv")

MFDS_API_URL = (
    "https://apis.data.go.kr/1471000/"
    "CsmtcsUseRstrcInfoService/"
    "getCsmtcsUseRstrcInfoService"
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


def s3_object_exists(key):
    s3 = get_s3_client()

    try:
        s3.head_object(
            Bucket=S3_BUCKET,
            Key=key,
        )
        return True

    except ClientError as error:
        code = (
            error.response
            .get("Error", {})
            .get("Code", "")
        )

        if code in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return False

        raise


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
        io.BytesIO(
            response["Body"].read()
        ),
        low_memory=False,
    )


def save_to_s3(df, key):
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

    for attempt in range(
        1,
        max_retries + 1,
    ):
        try:
            response = requests.get(
                MFDS_API_URL,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            header = data.get(
                "header",
                {},
            )

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
                "MFDS restriction request failed: "
                "page=%s, attempt=%s/%s, retry_in=%ss, error=%s",
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


def collect_restrictions():
    first_page = request_page(1)
    body = first_page.get(
        "body",
        {},
    )

    if "totalCount" not in body:
        raise RuntimeError(
            f"totalCount가 없습니다: {body}"
        )

    total_count = int(
        body["totalCount"]
    )
    total_pages = math.ceil(
        total_count / PAGE_SIZE
    )

    logger.info(
        "MFDS restriction collection: total=%s, pages=%s",
        f"{total_count:,}",
        f"{total_pages:,}",
    )

    rows = []

    for page_no in range(
        1,
        total_pages + 1,
    ):
        if (
            page_no == 1
            or page_no == total_pages
            or page_no % 20 == 0
        ):
            logger.info(
                "MFDS restriction progress: %s/%s",
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

        if page_no < total_pages:
            time.sleep(0.1)

    result = pd.DataFrame(rows)

    logger.info(
        "MFDS restriction rows collected: %s",
        f"{len(result):,}",
    )

    return result


def save_raw_restrictions(df):
    save_to_s3(
        df,
        S3_RESTRICTION_RAW_KEY,
    )


def load_dictionary():
    dictionary = load_csv_from_s3(
        S3_DICTIONARY_KEY
    )

    if "ingredient_key" not in dictionary.columns:
        raise ValueError(
            "ingredient_dictionary.csv에 "
            "ingredient_key 컬럼이 없습니다."
        )

    duplicate_count = (
        dictionary["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "ingredient_dictionary.csv에 "
            "ingredient_key 중복이 있습니다."
        )

    logger.info(
        "Loaded ingredient dictionary: %s",
        f"{len(dictionary):,}",
    )

    return dictionary


def join_unique(series):
    values = []

    for value in series:
        value = str(value).strip()

        if value and value not in values:
            values.append(value)

    return " | ".join(values)


def merge_regulate_type(series):
    values = {
        str(value).strip()
        for value in series
        if str(value).strip()
    }

    has_prohibited = any(
        "금지" in value
        for value in values
    )
    has_limited = any(
        "한도" in value
        for value in values
    )

    if has_prohibited and has_limited:
        return "한도/금지"

    if has_prohibited:
        return "금지"

    if has_limited:
        return "한도"

    return " | ".join(
        sorted(values)
    )


def prepare_korea_restrictions(df):
    if "COUNTRY_NAME" not in df.columns:
        raise ValueError(
            "식약처 규제 데이터에 COUNTRY_NAME 컬럼이 없습니다."
        )

    korea = df[
        df["COUNTRY_NAME"]
        .fillna("")
        .astype(str)
        .str.strip()
        .eq("한국")
    ].copy()

    logger.info(
        "Korea restriction source rows: %s",
        f"{len(korea):,}",
    )

    korea = korea.rename(
        columns={
            "INGR_STD_NAME": "regulation_ingredient_kr",
            "INGR_ENG_NAME": "regulation_ingredient_en",
            "CAS_NO": "regulation_cas_no",
            "INGR_SYNONYM": "regulation_synonym",
            "REGULATE_TYPE": "regulate_type",
            "LIMIT_COND": "limit_condition",
        }
    )

    columns = [
        "regulation_ingredient_kr",
        "regulation_ingredient_en",
        "regulation_cas_no",
        "regulation_synonym",
        "regulate_type",
        "limit_condition",
    ]

    for column in columns:
        if column not in korea.columns:
            korea[column] = ""

        korea[column] = (
            korea[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    korea["ingredient_key"] = korea[
        "regulation_ingredient_en"
    ].apply(normalize_ingredient_key)

    korea = korea[
        korea["ingredient_key"].ne("")
    ].copy()

    duplicate_rows = korea[
        korea["ingredient_key"].duplicated(
            keep=False
        )
    ].copy()

    logger.info(
        "Restriction duplicates before merge: "
        "rows=%s, keys=%s",
        f"{len(duplicate_rows):,}",
        f"{duplicate_rows['ingredient_key'].nunique():,}",
    )

    korea = (
        korea.groupby(
            "ingredient_key",
            as_index=False,
        )
        .agg(
            regulation_ingredient_kr=(
                "regulation_ingredient_kr",
                join_unique,
            ),
            regulation_ingredient_en=(
                "regulation_ingredient_en",
                join_unique,
            ),
            regulation_cas_no=(
                "regulation_cas_no",
                join_unique,
            ),
            regulation_synonym=(
                "regulation_synonym",
                join_unique,
            ),
            regulate_type=(
                "regulate_type",
                merge_regulate_type,
            ),
            limit_condition=(
                "limit_condition",
                join_unique,
            ),
        )
    )

    duplicate_count = (
        korea["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "한국 규제 데이터를 통합한 후에도 "
            "ingredient_key 중복이 있습니다."
        )

    logger.info(
        "Korea restriction keys after merge: %s",
        f"{len(korea):,}",
    )

    return korea


def apply_regulations(
    dictionary,
    korea_restrictions,
):
    result = dictionary.copy()
    before_count = len(result)

    regulation_columns = [
        "ingredient_key",
        "regulation_ingredient_kr",
        "regulation_ingredient_en",
        "regulation_cas_no",
        "regulation_synonym",
        "regulate_type",
        "limit_condition",
    ]

    result = result.merge(
        korea_restrictions[
            regulation_columns
        ],
        on="ingredient_key",
        how="left",
        validate="one_to_one",
    )

    if len(result) != before_count:
        raise RuntimeError(
            "규제 정보를 결합하면서 "
            "성분 행 수가 변경되었습니다."
        )

    text_columns = [
        "regulation_ingredient_kr",
        "regulation_ingredient_en",
        "regulation_cas_no",
        "regulation_synonym",
        "regulate_type",
        "limit_condition",
    ]

    result[text_columns] = (
        result[text_columns]
        .fillna("")
    )

    result["is_restricted"] = result[
        "regulate_type"
    ].ne("")

    result["is_prohibited"] = result[
        "regulate_type"
    ].str.contains(
        "금지",
        regex=False,
    )

    result["allowed"] = ~result[
        "is_prohibited"
    ]

    if "matched" in result.columns:
        result["needs_review"] = ~result[
            "matched"
        ]
    else:
        result["needs_review"] = False

    result["recommendable"] = result[
        "allowed"
    ]

    duplicate_count = (
        result["ingredient_key"]
        .duplicated()
        .sum()
    )

    if duplicate_count:
        raise RuntimeError(
            "규제 적용 후 ingredient_key 중복이 발생했습니다."
        )

    logger.info(
        "Regulation merge complete: %s rows",
        f"{len(result):,}",
    )

    return result


def save_result(df):
    save_to_s3(
        df,
        S3_OUTPUT_KEY,
    )


def log_summary(result):
    regulation_counts = (
        result["regulate_type"]
        .replace(
            "",
            "규제목록 없음",
        )
        .value_counts()
    )

    prohibited_count = int(
        result["regulate_type"]
        .str.contains(
            "금지",
            regex=False,
        )
        .sum()
    )

    limited_count = int(
        result["regulate_type"]
        .str.contains(
            "한도",
            regex=False,
        )
        .sum()
    )

    logger.info(
        "Regulation summary:\n%s",
        regulation_counts.to_string(),
    )
    logger.info(
        "prohibited=%s, limited=%s, recommendable=%s, needs_review=%s",
        f"{prohibited_count:,}",
        f"{limited_count:,}",
        f"{int(result['recommendable'].sum()):,}",
        f"{int(result['needs_review'].sum()):,}",
    )

    preview_columns = [
        column
        for column in [
            "ingredient_en",
            "ingredient_kr",
            "regulate_type",
            "limit_condition",
        ]
        if column in result.columns
    ]

    prohibited = result[
        result["is_prohibited"]
    ]

    if not prohibited.empty:
        logger.info(
            "Prohibited ingredient sample:\n%s",
            prohibited[
                preview_columns
            ]
            .head(20)
            .to_string(index=False),
        )

    limited = result[
        result["regulate_type"].str.contains(
            "한도",
            regex=False,
        )
    ]

    if not limited.empty:
        logger.info(
            "Limited ingredient sample:\n%s",
            limited[
                preview_columns
            ]
            .head(10)
            .to_string(index=False),
        )


def main():
    if s3_object_exists(
        S3_RESTRICTION_RAW_KEY
    ):
        logger.info(
            "Using cached MFDS restriction data from S3."
        )
        restrictions = load_csv_from_s3(
            S3_RESTRICTION_RAW_KEY
        )
    else:
        restrictions = collect_restrictions()
        save_raw_restrictions(
            restrictions
        )

    dictionary = load_dictionary()

    korea_restrictions = (
        prepare_korea_restrictions(
            restrictions
        )
    )

    result = apply_regulations(
        dictionary,
        korea_restrictions,
    )

    log_summary(result)
    save_result(result)


if __name__ == "__main__":
    main()

import ast
import logging
import os
import re
from datetime import timedelta
from io import BytesIO, StringIO

import boto3
import pandas as pd
import pendulum
import pymysql
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator


logger = logging.getLogger(__name__)


AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
BUCKET_NAME = os.getenv( "S3_BUCKET_NAME","recommender-data-mj-881050425460-ap-northeast-2-an",)

RAW_PRODUCT_KEY = "raw/sephora/product_info.csv"
PARSED_PRODUCT_KEY = ("processed/cosmetics/_stage/product_ingredients_parsed.csv")
CLEAN_PRODUCT_KEY = ( "processed/cosmetics/_stage/product_ingredients_clean.csv")
QUARANTINE_KEY = ("processed/cosmetics/_quality/suspicious_ingredients.csv")
FINAL_PRODUCT_KEY = "processed/cosmetics/product_ingredients.csv"
INGREDIENT_DICTIONARY_KEY = ("processed/cosmetics/ingredient_dictionary.csv")

DB_HOST = os.getenv("DB_HOST", "mariadb")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "recommender")
DB_USER = os.getenv("DB_USER", "recommender")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def get_s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def read_csv_from_s3(key):
    s3 = get_s3_client()
    logger.info("S3 read: s3://%s/%s", BUCKET_NAME, key)

    response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
    data = response["Body"].read()
    df = pd.read_csv(BytesIO(data), low_memory=False)

    logger.info("Loaded %s rows x %s columns", len(df), len(df.columns))
    return df


def save_csv_to_s3(df, key):
    s3 = get_s3_client()

    buffer = StringIO()
    df.to_csv(buffer, index=False)

    body = ("\ufeff" + buffer.getvalue()).encode("utf-8")
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=body,
        ContentType="text/csv; charset=utf-8",
    )

    logger.info(
        "S3 save: s3://%s/%s (%s rows x %s columns)",
        BUCKET_NAME,
        key,
        len(df),
        len(df.columns),
    )


def get_db_connection():
    if not DB_PASSWORD:
        raise RuntimeError(
            "DB_PASSWORD 환경변수가 설정되지 않았습니다."
        )

    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )


def parse_ingredient_value(value):
    if pd.isna(value):
        return []

    text = str(value).strip()
    if not text:
        return []

    try:
        parsed = ast.literal_eval(text)
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

    ingredients = []

    for item in items:
        item = item.strip()
        if not item:
            continue

        if item.lower() in {"ingredients", "ingredients:"}:
            continue

        # 1,2-Hexanediol처럼 숫자 사이의 쉼표는 성분 구분자로 보지 않는다.
        protected = re.sub(
            r"(?<=\d),(?=\s*\d)",
            "<NUM_COMMA>",
            item,
        )

        for part in re.split(r"[,;\n]+", protected):
            ingredient = (
                part.replace("<NUM_COMMA>", ",").strip()
            )
            if ingredient:
                ingredients.append(ingredient)

    return ingredients


def clean_ingredient_name(value):
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\-\*\•\·]+", "", text).strip()
    text = re.sub(r"\.+$", "", text).strip()

    return text or None


def make_ingredient_key(value):
    if pd.isna(value):
        return None

    text = str(value).lower().strip()
    if not text:
        return None

    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9가-힣]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text.replace(" ", "_") if text else None


def is_suspicious_ingredient(value):
    if pd.isna(value):
        return False

    text = str(value).strip()
    if not text:
        return False

    char_count = len(text)
    word_count = len(text.split())
    ci_count = len(
        re.findall(
            r"\bci\s*\d{5}\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    suspicious_phrases = {
        "corporate regulatory",
        "regulatory affairs",
        "allergen substances",
        "allergen substance",
        "the allergen",
    }
    lower_text = text.lower()

    return any(
        [
            char_count > 100,
            word_count > 12,
            ci_count >= 3,
            any(
                phrase in lower_text
                for phrase in suspicious_phrases
            ),
        ]
    )


def load_products():
    df = read_csv_from_s3(RAW_PRODUCT_KEY)

    required_columns = {
        "product_id",
        "product_name",
        "ingredients",
    }
    missing_columns = sorted(
        required_columns - set(df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"필수 컬럼이 없습니다: {missing_columns}"
        )

    logger.info(
        "Product source check: rows=%s, columns=%s",
        f"{len(df):,}",
        len(df.columns),
    )
    logger.info(
        "ingredients missing=%s, present=%s",
        f"{df['ingredients'].isna().sum():,}",
        f"{df['ingredients'].notna().sum():,}",
    )


def parse_ingredients():
    df = read_csv_from_s3(RAW_PRODUCT_KEY)

    df["ingredient_list"] = df["ingredients"].apply(
        parse_ingredient_value
    )
    df["ingredient_count"] = df["ingredient_list"].apply(
        len
    )

    logger.info(
        "Average ingredients per product: %.2f",
        df["ingredient_count"].mean(),
    )
    logger.info(
        "Products with no parsed ingredients: %s",
        f"{(df['ingredient_count'] == 0).sum():,}",
    )

    exploded = (
        df.explode("ingredient_list")
        .reset_index(drop=True)
        .rename(
            columns={
                "ingredient_list": "ingredient_raw"
            }
        )
    )

    output_columns = [
        "product_id",
        "product_name",
    ]
    optional_columns = [
        "brand_id",
        "brand_name",
        "primary_category",
        "secondary_category",
        "tertiary_category",
        "price_usd",
        "rating",
        "reviews",
    ]

    output_columns.extend(
        col
        for col in optional_columns
        if col in exploded.columns
    )
    output_columns.append("ingredient_raw")

    parsed_df = exploded[output_columns].copy()
    parsed_df = parsed_df[
        parsed_df["ingredient_raw"].notna()
    ].copy()

    parsed_df["ingredient_raw"] = (
        parsed_df["ingredient_raw"]
        .astype(str)
        .str.strip()
    )
    parsed_df = (
        parsed_df[
            parsed_df["ingredient_raw"] != ""
        ]
        .reset_index(drop=True)
    )

    logger.info(
        "Parsed product-ingredient rows: %s",
        f"{len(parsed_df):,}",
    )
    logger.info(
        "Parsed sample:\n%s",
        parsed_df[
            [
                "product_id",
                "product_name",
                "ingredient_raw",
            ]
        ]
        .head(10)
        .to_string(index=False),
    )

    save_csv_to_s3(
        parsed_df,
        PARSED_PRODUCT_KEY,
    )


def clean_ingredients():
    df = read_csv_from_s3(PARSED_PRODUCT_KEY)

    df["ingredient_name"] = df[
        "ingredient_raw"
    ].apply(clean_ingredient_name)

    df = df[
        df["ingredient_name"].notna()
    ].copy()

    df["is_suspicious"] = df[
        "ingredient_name"
    ].apply(is_suspicious_ingredient)

    suspicious_df = (
        df[df["is_suspicious"]]
        .copy()
        .reset_index(drop=True)
    )
    clean_df = (
        df[~df["is_suspicious"]]
        .copy()
        .reset_index(drop=True)
    )

    total_count = len(df)
    suspicious_count = len(suspicious_df)
    suspicious_ratio = (
        suspicious_count / total_count * 100
        if total_count
        else 0
    )

    logger.info(
        "Ingredient quality check: total=%s, clean=%s, quarantine=%s (%.2f%%)",
        f"{total_count:,}",
        f"{len(clean_df):,}",
        f"{suspicious_count:,}",
        suspicious_ratio,
    )

    if not suspicious_df.empty:
        suspicious_df["char_count"] = (
            suspicious_df["ingredient_name"]
            .astype(str)
            .str.len()
        )
        suspicious_df["word_count"] = (
            suspicious_df["ingredient_name"]
            .astype(str)
            .str.split()
            .str.len()
        )
        suspicious_df["ci_count"] = (
            suspicious_df["ingredient_name"]
            .astype(str)
            .apply(
                lambda value: len(
                    re.findall(
                        r"\bci\s*\d{5}\b",
                        value,
                        flags=re.IGNORECASE,
                    )
                )
            )
        )

        save_csv_to_s3(
            suspicious_df,
            QUARANTINE_KEY,
        )

        logger.info(
            "Quarantine sample:\n%s",
            suspicious_df[
                [
                    "ingredient_name",
                    "char_count",
                    "word_count",
                    "ci_count",
                ]
            ]
            .sort_values(
                "char_count",
                ascending=False,
            )
            .head(10)
            .to_string(index=False),
        )

    clean_df["ingredient_key"] = clean_df[
        "ingredient_name"
    ].apply(make_ingredient_key)

    clean_df = clean_df[
        clean_df["ingredient_key"].notna()
        & (clean_df["ingredient_key"] != "")
    ].copy()

    before = len(clean_df)
    clean_df = (
        clean_df.drop_duplicates(
            subset=[
                "product_id",
                "ingredient_key",
            ]
        )
        .reset_index(drop=True)
    )

    logger.info(
        "Removed duplicate product-ingredient pairs: %s",
        f"{before - len(clean_df):,}",
    )
    logger.info(
        "Final clean product-ingredient rows: %s",
        f"{len(clean_df):,}",
    )
    logger.info(
        "Unique ingredient keys: %s",
        f"{clean_df['ingredient_key'].nunique():,}",
    )

    clean_df = clean_df.drop(
        columns=["is_suspicious"],
        errors="ignore",
    )

    save_csv_to_s3(
        clean_df,
        CLEAN_PRODUCT_KEY,
    )


def save_processed_data():
    df = read_csv_from_s3(CLEAN_PRODUCT_KEY)

    final_df = (
        df.drop_duplicates(
            subset=[
                "product_id",
                "ingredient_key",
            ]
        )
        .reset_index(drop=True)
    )

    save_csv_to_s3(
        final_df,
        FINAL_PRODUCT_KEY,
    )

    ingredient_dictionary = (
        final_df.groupby(
            [
                "ingredient_key",
                "ingredient_name",
            ],
            as_index=False,
        )
        .agg(
            product_count=(
                "product_id",
                "nunique",
            )
        )
        .sort_values(
            [
                "product_count",
                "ingredient_key",
            ],
            ascending=[
                False,
                True,
            ],
        )
        .reset_index(drop=True)
    )

    save_csv_to_s3(
        ingredient_dictionary,
        INGREDIENT_DICTIONARY_KEY,
    )

    logger.info(
        "Processed product-ingredient rows: %s",
        f"{len(final_df):,}",
    )
    logger.info(
        "Products with parsed ingredients: %s",
        f"{final_df['product_id'].nunique():,}",
    )
    logger.info(
        "Unique ingredient keys: %s",
        f"{final_df['ingredient_key'].nunique():,}",
    )
    logger.info(
        "Top ingredients:\n%s",
        ingredient_dictionary.head(20).to_string(
            index=False
        ),
    )


def _to_db_value(value):
    return None if pd.isna(value) else value


def _insert_dataframe(
    cursor,
    table_name,
    df,
    columns,
    batch_size=1000,
):
    placeholders = ", ".join(
        ["%s"] * len(columns)
    )
    column_sql = ", ".join(
        f"`{column}`"
        for column in columns
    )
    sql = (
        f"INSERT INTO `{table_name}` "
        f"({column_sql}) "
        f"VALUES ({placeholders})"
    )

    total = len(df)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_df = df.iloc[start:end]

        rows = [
            tuple(
                _to_db_value(row[column])
                for column in columns
            )
            for _, row in batch_df.iterrows()
        ]

        cursor.executemany(sql, rows)
        logger.info(
            "%s: %s/%s rows inserted",
            table_name,
            f"{end:,}",
            f"{total:,}",
        )


def load_to_mariadb():
    product_df = read_csv_from_s3(
        FINAL_PRODUCT_KEY
    )
    dictionary_df = read_csv_from_s3(
        INGREDIENT_DICTIONARY_KEY
    )

    product_columns = [
        "product_id",
        "product_name",
        "brand_id",
        "brand_name",
        "primary_category",
        "secondary_category",
        "tertiary_category",
        "price_usd",
        "rating",
        "reviews",
        "ingredient_raw",
        "ingredient_name",
        "ingredient_key",
    ]
    dictionary_columns = [
        "ingredient_key",
        "ingredient_name",
        "product_count",
    ]

    for column in product_columns:
        if column not in product_df.columns:
            product_df[column] = None

    for column in dictionary_columns:
        if column not in dictionary_df.columns:
            dictionary_df[column] = None

    product_df = product_df[
        product_columns
    ].copy()
    dictionary_df = dictionary_df[
        dictionary_columns
    ].copy()

    logger.info(
        "Rows to load: product_ingredients=%s, ingredient_dictionary=%s",
        f"{len(product_df):,}",
        f"{len(dictionary_df):,}",
    )

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS product_ingredients (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    product_id VARCHAR(64) NOT NULL,
                    product_name TEXT NULL,
                    brand_id VARCHAR(64) NULL,
                    brand_name VARCHAR(255) NULL,
                    primary_category VARCHAR(255) NULL,
                    secondary_category VARCHAR(255) NULL,
                    tertiary_category VARCHAR(255) NULL,
                    price_usd DOUBLE NULL,
                    rating DOUBLE NULL,
                    reviews BIGINT NULL,
                    ingredient_raw TEXT NULL,
                    ingredient_name VARCHAR(512) NOT NULL,
                    ingredient_key VARCHAR(512) NOT NULL,
                    PRIMARY KEY (id),
                    KEY idx_product_id (product_id),
                    KEY idx_ingredient_key (ingredient_key(191))
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ingredient_dictionary (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    ingredient_key VARCHAR(512) NOT NULL,
                    ingredient_name VARCHAR(512) NOT NULL,
                    product_count BIGINT NOT NULL,
                    PRIMARY KEY (id),
                    KEY idx_dictionary_key (ingredient_key(191)),
                    KEY idx_product_count (product_count)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            for table_name in [
                "product_ingredients_staging",
                "ingredient_dictionary_staging",
                "product_ingredients_old",
                "ingredient_dictionary_old",
            ]:
                cursor.execute(
                    f"DROP TABLE IF EXISTS `{table_name}`"
                )

            cursor.execute(
                """
                CREATE TABLE product_ingredients_staging
                LIKE product_ingredients
                """
            )
            cursor.execute(
                """
                CREATE TABLE ingredient_dictionary_staging
                LIKE ingredient_dictionary
                """
            )

            _insert_dataframe(
                cursor,
                "product_ingredients_staging",
                product_df,
                product_columns,
            )
            _insert_dataframe(
                cursor,
                "ingredient_dictionary_staging",
                dictionary_df,
                dictionary_columns,
            )

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM product_ingredients_staging
                """
            )
            product_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM ingredient_dictionary_staging
                """
            )
            dictionary_count = cursor.fetchone()[0]

            if product_count != len(product_df):
                raise ValueError(
                    "product_ingredients staging 건수 불일치: "
                    f"S3={len(product_df):,}, "
                    f"DB={product_count:,}"
                )

            if dictionary_count != len(
                dictionary_df
            ):
                raise ValueError(
                    "ingredient_dictionary staging 건수 불일치: "
                    f"S3={len(dictionary_df):,}, "
                    f"DB={dictionary_count:,}"
                )

            connection.commit()

            cursor.execute(
                """
                RENAME TABLE
                    product_ingredients
                        TO product_ingredients_old,
                    product_ingredients_staging
                        TO product_ingredients,
                    ingredient_dictionary
                        TO ingredient_dictionary_old,
                    ingredient_dictionary_staging
                        TO ingredient_dictionary
                """
            )

            cursor.execute(
                "DROP TABLE product_ingredients_old"
            )
            cursor.execute(
                "DROP TABLE ingredient_dictionary_old"
            )

        connection.commit()

        logger.info(
            "MariaDB load complete: product_ingredients=%s, "
            "ingredient_dictionary=%s",
            f"{product_count:,}",
            f"{dictionary_count:,}",
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def load_products_to_mariadb():
    df = read_csv_from_s3(RAW_PRODUCT_KEY)

    product_columns = [
        "product_id",
        "product_name",
        "brand_id",
        "brand_name",
        "loves_count",
        "rating",
        "reviews",
        "size",
        "variation_type",
        "variation_value",
        "variation_desc",
        "ingredients",
        "price_usd",
        "value_price_usd",
        "sale_price_usd",
        "limited_edition",
        "new",
        "online_only",
        "out_of_stock",
        "sephora_exclusive",
        "highlights",
        "primary_category",
        "secondary_category",
        "tertiary_category",
        "child_count",
        "child_max_price",
        "child_min_price",
    ]

    for column in product_columns:
        if column not in df.columns:
            df[column] = None

    products = df[product_columns].copy()

    products["product_id"] = (
        products["product_id"]
        .astype("string")
        .str.strip()
    )
    products = products[
        products["product_id"].notna()
        & (products["product_id"] != "")
    ].copy()

    products = (
        products.drop_duplicates(
            subset=["product_id"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    numeric_columns = [
        "loves_count",
        "rating",
        "reviews",
        "price_usd",
        "value_price_usd",
        "sale_price_usd",
        "limited_edition",
        "new",
        "online_only",
        "out_of_stock",
        "sephora_exclusive",
        "child_count",
        "child_max_price",
        "child_min_price",
    ]

    for column in numeric_columns:
        products[column] = pd.to_numeric(
            products[column],
            errors="coerce",
        )

    ingredient_text = (
        products["ingredients"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    products["has_ingredients"] = (
        ingredient_text != ""
    ).astype(int)

    parsed_df = read_csv_from_s3(
        FINAL_PRODUCT_KEY
    )
    parsed_product_ids = set(
        parsed_df["product_id"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
    )

    def get_parse_status(row):
        if row["has_ingredients"] == 0:
            return "missing"

        if (
            str(row["product_id"]).strip()
            in parsed_product_ids
        ):
            return "parsed"

        return "unparsed"

    products["ingredient_parse_status"] = (
        products.apply(
            get_parse_status,
            axis=1,
        )
    )

    db_columns = product_columns + [
        "has_ingredients",
        "ingredient_parse_status",
    ]

    logger.info(
        "Products to load: %s",
        f"{len(products):,}",
    )
    logger.info(
        "Products with ingredients: %s",
        f"{products['has_ingredients'].sum():,}",
    )
    logger.info(
        "Products without ingredients: %s",
        f"{(products['has_ingredients'] == 0).sum():,}",
    )
    logger.info(
        "Parse status:\n%s",
        products[
            "ingredient_parse_status"
        ]
        .value_counts(dropna=False)
        .to_string(),
    )

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_id VARCHAR(64) NOT NULL,
                    product_name TEXT NULL,
                    brand_id VARCHAR(64) NULL,
                    brand_name VARCHAR(255) NULL,
                    loves_count BIGINT NULL,
                    rating DOUBLE NULL,
                    reviews BIGINT NULL,
                    size VARCHAR(255) NULL,
                    variation_type VARCHAR(255) NULL,
                    variation_value VARCHAR(255) NULL,
                    variation_desc TEXT NULL,
                    ingredients LONGTEXT NULL,
                    price_usd DOUBLE NULL,
                    value_price_usd DOUBLE NULL,
                    sale_price_usd DOUBLE NULL,
                    limited_edition TINYINT NULL,
                    `new` TINYINT NULL,
                    online_only TINYINT NULL,
                    out_of_stock TINYINT NULL,
                    sephora_exclusive TINYINT NULL,
                    highlights LONGTEXT NULL,
                    primary_category VARCHAR(255) NULL,
                    secondary_category VARCHAR(255) NULL,
                    tertiary_category VARCHAR(255) NULL,
                    child_count BIGINT NULL,
                    child_max_price DOUBLE NULL,
                    child_min_price DOUBLE NULL,
                    has_ingredients TINYINT NOT NULL,
                    ingredient_parse_status VARCHAR(20) NOT NULL,
                    PRIMARY KEY (product_id),
                    KEY idx_products_brand_name (brand_name),
                    KEY idx_products_primary_category (primary_category),
                    KEY idx_products_secondary_category (secondary_category),
                    KEY idx_products_has_ingredients (has_ingredients),
                    KEY idx_products_parse_status (ingredient_parse_status)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = 'products'
                  AND COLUMN_NAME = 'ingredient_parse_status'
                """,
                (DB_NAME,),
            )

            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    """
                    ALTER TABLE products
                    ADD COLUMN ingredient_parse_status
                    VARCHAR(20) NOT NULL
                    DEFAULT 'missing'
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX idx_products_parse_status
                    ON products (ingredient_parse_status)
                    """
                )

            cursor.execute(
                "TRUNCATE TABLE products"
            )

            _insert_dataframe(
                cursor,
                "products",
                products,
                db_columns,
            )

            cursor.execute(
                "SELECT COUNT(*) FROM products"
            )
            db_count = cursor.fetchone()[0]

            if db_count != len(products):
                raise ValueError(
                    "products 적재 건수 불일치: "
                    f"S3={len(products):,}, "
                    f"DB={db_count:,}"
                )

        connection.commit()

        logger.info(
            "Product master load complete: %s rows",
            f"{db_count:,}",
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


with DAG(
    dag_id="ingredient_pipeline",
    description=(
        "Sephora ingredient ETL and data quality pipeline"
    ),
    start_date=pendulum.datetime(
        2026,
        9,
        1,
        tz="Asia/Seoul",
    ),
    schedule="0 3 * * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    tags=[
        "recommendation",
        "sephora",
        "ingredient",
        "s3",
        "etl",
        "data-quality",
    ],
) as dag:
    load_products_task = PythonOperator(
        task_id="load_products",
        python_callable=load_products,
    )

    parse_ingredients_task = PythonOperator(
        task_id="parse_ingredients",
        python_callable=parse_ingredients,
    )

    clean_ingredients_task = PythonOperator(
        task_id="clean_ingredients",
        python_callable=clean_ingredients,
    )

    save_processed_data_task = PythonOperator(
        task_id="save_processed_data",
        python_callable=save_processed_data,
    )

    load_products_to_mariadb_task = PythonOperator(
        task_id="load_products_to_mariadb",
        python_callable=load_products_to_mariadb,
    )

    load_to_mariadb_task = PythonOperator(
        task_id="load_to_mariadb",
        python_callable=load_to_mariadb,
    )

    (
        load_products_task
        >> parse_ingredients_task
        >> clean_ingredients_task
        >> save_processed_data_task
        >> load_products_to_mariadb_task
        >> load_to_mariadb_task
    )

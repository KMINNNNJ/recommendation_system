import logging
import os
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
BUCKET_NAME = os.getenv("S3_BUCKET_NAME","recommender-data-mj-881050425460-ap-northeast-2-an",)

RAW_REVIEW_KEY = "raw/sephora/reviews_all.csv"
CLEAN_REVIEW_KEY = "processed/reviews/reviews_clean.csv"
INTERACTION_KEY = "processed/reviews/user_item_interactions.csv"
REVIEW_QUARANTINE_KEY = ("processed/reviews/_quality/invalid_reviews.csv")

DB_HOST = os.getenv("MARIADB_HOST", "mariadb")
DB_PORT = int(os.getenv("MARIADB_PORT", "3306"))
DB_NAME = os.getenv("MARIADB_DATABASE", "recommender")
DB_USER = os.getenv("MARIADB_USER", "recommender")
DB_PASSWORD = os.getenv("MARIADB_PASSWORD")


def get_s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def read_csv_from_s3(key):
    s3 = get_s3_client()
    logger.info("S3 read: s3://%s/%s", BUCKET_NAME, key)

    response = s3.get_object(Bucket=BUCKET_NAME, Key=key,)
    data = response["Body"].read()

    df = pd.read_csv(BytesIO(data), low_memory=False,)

    logger.info(
        "Loaded %s rows x %s columns",
        len(df),
        len(df.columns),
    )
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
            "MARIADB_PASSWORD 환경변수가 설정되지 않았습니다."
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


def normalize_boolean(value):
    if pd.isna(value):
        return None

    if isinstance(value, bool):
        return int(value)

    text = str(value).strip().lower()

    true_values = {
        "1",
        "1.0",
        "true",
        "yes",
        "y",
        "recommended",
    }
    false_values = {
        "0",
        "0.0",
        "false",
        "no",
        "n",
        "not recommended",
    }

    if text in true_values:
        return 1

    if text in false_values:
        return 0

    return None


def _to_db_value(value):
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass

    return value


def _insert_dataframe(
    cursor,
    table_name,
    df,
    columns,
    batch_size=5000,
):
    placeholders = ", ".join(["%s"] * len(columns))
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


def load_reviews():
    df = read_csv_from_s3(RAW_REVIEW_KEY)

    required_columns = {
        "author_id",
        "product_id",
        "rating",
    }
    missing_columns = sorted(
        required_columns - set(df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"필수 컬럼이 없습니다: {missing_columns}"
        )

    logger.info(
        "Review source check: rows=%s, columns=%s",
        f"{len(df):,}",
        len(df.columns),
    )
    logger.info(
        "Missing values: author_id=%s, product_id=%s, rating=%s",
        f"{df['author_id'].isna().sum():,}",
        f"{df['product_id'].isna().sum():,}",
        f"{df['rating'].isna().sum():,}",
    )


def clean_reviews():
    df = read_csv_from_s3(RAW_REVIEW_KEY)

    df["author_id"] = (
        df["author_id"]
        .astype("string")
        .str.strip()
    )
    df["product_id"] = (
        df["product_id"]
        .astype("string")
        .str.strip()
    )

    invalid_id_values = {
        "",
        "nan",
        "none",
        "<na>",
    }

    author_bad = (
        df["author_id"]
        .fillna("")
        .str.lower()
        .isin(invalid_id_values)
    )
    product_bad = (
        df["product_id"]
        .fillna("")
        .str.lower()
        .isin(invalid_id_values)
    )

    df["rating"] = pd.to_numeric(
        df["rating"],
        errors="coerce",
    )
    rating_bad = (
        df["rating"].isna()
        | (df["rating"] < 1)
        | (df["rating"] > 5)
    )

    invalid_mask = (
        author_bad
        | product_bad
        | rating_bad
    )

    invalid_df = (
        df[invalid_mask]
        .copy()
        .reset_index(drop=True)
    )
    clean_df = (
        df[~invalid_mask]
        .copy()
        .reset_index(drop=True)
    )

    logger.info(
        "Review quality check: total=%s, valid=%s, quarantine=%s",
        f"{len(df):,}",
        f"{len(clean_df):,}",
        f"{len(invalid_df):,}",
    )

    if "is_recommended" in clean_df.columns:
        clean_df["is_recommended"] = clean_df[
            "is_recommended"
        ].apply(normalize_boolean)
    else:
        clean_df["is_recommended"] = None

    if "helpfulness" in clean_df.columns:
        clean_df["helpfulness"] = pd.to_numeric(
            clean_df["helpfulness"],
            errors="coerce",
        ).clip(
            lower=0,
            upper=1,
        )
    else:
        clean_df["helpfulness"] = None

    if "submission_time" in clean_df.columns:
        clean_df["submission_time"] = pd.to_datetime(
            clean_df["submission_time"],
            errors="coerce",
        )
    else:
        clean_df["submission_time"] = pd.NaT

    optional_columns = [
        "product_name",
        "brand_name",
        "price_usd",
        "skin_type",
        "skin_tone",
        "eye_color",
        "hair_color",
        "total_feedback_count",
        "total_neg_feedback_count",
        "total_pos_feedback_count",
    ]

    for column in optional_columns:
        if column not in clean_df.columns:
            clean_df[column] = None

    numeric_columns = [
        "price_usd",
        "total_feedback_count",
        "total_neg_feedback_count",
        "total_pos_feedback_count",
    ]

    for column in numeric_columns:
        clean_df[column] = pd.to_numeric(
            clean_df[column],
            errors="coerce",
        )

    output_columns = [
        "author_id",
        "product_id",
        "rating",
        "is_recommended",
        "helpfulness",
        "submission_time",
        "product_name",
        "brand_name",
        "price_usd",
        "skin_type",
        "skin_tone",
        "eye_color",
        "hair_color",
        "total_feedback_count",
        "total_neg_feedback_count",
        "total_pos_feedback_count",
    ]

    clean_df = clean_df[output_columns].copy()

    before = len(clean_df)
    clean_df = (
        clean_df.drop_duplicates()
        .reset_index(drop=True)
    )

    logger.info(
        "Removed duplicate reviews: %s",
        f"{before - len(clean_df):,}",
    )
    logger.info(
        "Final clean reviews: %s",
        f"{len(clean_df):,}",
    )

    save_csv_to_s3(
        clean_df,
        CLEAN_REVIEW_KEY,
    )

    if not invalid_df.empty:
        save_csv_to_s3(
            invalid_df,
            REVIEW_QUARANTINE_KEY,
        )


def create_interactions():
    df = read_csv_from_s3(CLEAN_REVIEW_KEY)

    df["submission_time"] = pd.to_datetime(
        df["submission_time"],
        errors="coerce",
    )

    interactions = (
        df.groupby(
            [
                "author_id",
                "product_id",
            ],
            as_index=False,
        )
        .agg(
            rating=("rating", "mean"),
            review_count=("rating", "size"),
            recommend_rate=(
                "is_recommended",
                "mean",
            ),
            mean_helpfulness=(
                "helpfulness",
                "mean",
            ),
            last_submission_time=(
                "submission_time",
                "max",
            ),
        )
    )

    # Baseline에서는 별도 가중치 없이 평균 평점을 사용한다.
    interactions["interaction_score"] = (
        interactions["rating"]
    )

    round_columns = [
        "rating",
        "recommend_rate",
        "mean_helpfulness",
        "interaction_score",
    ]
    interactions[round_columns] = interactions[
        round_columns
    ].round(4)

    logger.info(
        "Interactions: %s, users=%s, products=%s",
        f"{len(interactions):,}",
        f"{interactions['author_id'].nunique():,}",
        f"{interactions['product_id'].nunique():,}",
    )
    logger.info(
        "Interaction sample:\n%s",
        interactions.head(10).to_string(index=False),
    )

    save_csv_to_s3(
        interactions,
        INTERACTION_KEY,
    )


def validate_review_outputs():
    reviews = read_csv_from_s3(
        CLEAN_REVIEW_KEY
    )
    interactions = read_csv_from_s3(
        INTERACTION_KEY
    )

    if reviews.empty:
        raise ValueError(
            "reviews_clean.csv가 비어 있습니다."
        )

    if interactions.empty:
        raise ValueError(
            "user_item_interactions.csv가 비어 있습니다."
        )

    if reviews["author_id"].isna().any():
        raise ValueError(
            "reviews_clean에 author_id 결측이 있습니다."
        )

    if reviews["product_id"].isna().any():
        raise ValueError(
            "reviews_clean에 product_id 결측이 있습니다."
        )

    if not reviews["rating"].between(1, 5).all():
        raise ValueError(
            "rating 범위 오류가 있습니다."
        )

    duplicated_pairs = interactions.duplicated(
        subset=[
            "author_id",
            "product_id",
        ]
    ).sum()

    if duplicated_pairs > 0:
        raise ValueError(
            "interaction에 중복된 user-product pair가 있습니다."
        )

    logger.info(
        "Validation complete: reviews=%s, interactions=%s, "
        "duplicate_pairs=%s, rating_range=(%s, %s)",
        f"{len(reviews):,}",
        f"{len(interactions):,}",
        duplicated_pairs,
        reviews["rating"].min(),
        reviews["rating"].max(),
    )


def load_reviews_to_mariadb():
    reviews = read_csv_from_s3(
        CLEAN_REVIEW_KEY
    )
    interactions = read_csv_from_s3(
        INTERACTION_KEY
    )

    review_columns = [
        "author_id",
        "product_id",
        "rating",
        "is_recommended",
        "helpfulness",
        "submission_time",
        "product_name",
        "brand_name",
        "price_usd",
        "skin_type",
        "skin_tone",
        "eye_color",
        "hair_color",
        "total_feedback_count",
        "total_neg_feedback_count",
        "total_pos_feedback_count",
    ]

    interaction_columns = [
        "author_id",
        "product_id",
        "rating",
        "interaction_score",
        "review_count",
        "recommend_rate",
        "mean_helpfulness",
        "last_submission_time",
    ]

    for column in review_columns:
        if column not in reviews.columns:
            reviews[column] = None

    for column in interaction_columns:
        if column not in interactions.columns:
            interactions[column] = None

    reviews = reviews[review_columns].copy()
    interactions = interactions[
        interaction_columns
    ].copy()

    logger.info(
        "Rows to load: reviews=%s, interactions=%s",
        f"{len(reviews):,}",
        f"{len(interactions):,}",
    )

    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    author_id VARCHAR(128) NOT NULL,
                    product_id VARCHAR(64) NOT NULL,
                    rating DOUBLE NOT NULL,
                    is_recommended TINYINT NULL,
                    helpfulness DOUBLE NULL,
                    submission_time DATETIME NULL,
                    product_name TEXT NULL,
                    brand_name VARCHAR(255) NULL,
                    price_usd DOUBLE NULL,
                    skin_type VARCHAR(100) NULL,
                    skin_tone VARCHAR(100) NULL,
                    eye_color VARCHAR(100) NULL,
                    hair_color VARCHAR(100) NULL,
                    total_feedback_count BIGINT NULL,
                    total_neg_feedback_count BIGINT NULL,
                    total_pos_feedback_count BIGINT NULL,
                    PRIMARY KEY (id),
                    KEY idx_reviews_author (author_id),
                    KEY idx_reviews_product (product_id),
                    KEY idx_reviews_author_product (
                        author_id,
                        product_id
                    )
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_item_interactions (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    author_id VARCHAR(128) NOT NULL,
                    product_id VARCHAR(64) NOT NULL,
                    rating DOUBLE NOT NULL,
                    interaction_score DOUBLE NOT NULL,
                    review_count BIGINT NOT NULL,
                    recommend_rate DOUBLE NULL,
                    mean_helpfulness DOUBLE NULL,
                    last_submission_time DATETIME NULL,
                    PRIMARY KEY (id),
                    UNIQUE KEY uq_user_product (
                        author_id,
                        product_id
                    ),
                    KEY idx_interaction_author (author_id),
                    KEY idx_interaction_product (product_id)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            for table_name in [
                "reviews_staging",
                "user_item_interactions_staging",
                "reviews_old",
                "user_item_interactions_old",
            ]:
                cursor.execute(
                    f"DROP TABLE IF EXISTS `{table_name}`"
                )

            cursor.execute(
                """
                CREATE TABLE reviews_staging
                LIKE reviews
                """
            )
            cursor.execute(
                """
                CREATE TABLE user_item_interactions_staging
                LIKE user_item_interactions
                """
            )

            _insert_dataframe(
                cursor,
                "reviews_staging",
                reviews,
                review_columns,
                batch_size=5000,
            )
            _insert_dataframe(
                cursor,
                "user_item_interactions_staging",
                interactions,
                interaction_columns,
                batch_size=5000,
            )

            cursor.execute(
                "SELECT COUNT(*) FROM reviews_staging"
            )
            db_review_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM user_item_interactions_staging
                """
            )
            db_interaction_count = cursor.fetchone()[0]

            if db_review_count != len(reviews):
                raise ValueError(
                    "reviews staging 적재 건수 불일치: "
                    f"S3={len(reviews):,}, "
                    f"DB={db_review_count:,}"
                )

            if db_interaction_count != len(
                interactions
            ):
                raise ValueError(
                    "interaction staging 적재 건수 불일치: "
                    f"S3={len(interactions):,}, "
                    f"DB={db_interaction_count:,}"
                )

            connection.commit()

            cursor.execute(
                """
                RENAME TABLE
                    reviews
                        TO reviews_old,
                    reviews_staging
                        TO reviews,
                    user_item_interactions
                        TO user_item_interactions_old,
                    user_item_interactions_staging
                        TO user_item_interactions
                """
            )

            cursor.execute(
                "DROP TABLE reviews_old"
            )
            cursor.execute(
                "DROP TABLE user_item_interactions_old"
            )

        connection.commit()

        logger.info(
            "MariaDB load complete: reviews=%s, interactions=%s",
            f"{db_review_count:,}",
            f"{db_interaction_count:,}",
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


with DAG(
    dag_id="review_pipeline",
    description=(
        "Sephora review ETL, interaction generation, "
        "and MariaDB loading pipeline"
    ),
    start_date=pendulum.datetime(
        2026,
        9,
        1,
        tz="Asia/Seoul",
    ),
    schedule="0 4 * * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    tags=[
        "recommendation",
        "sephora",
        "review",
        "interaction",
        "s3",
        "mariadb",
        "etl",
    ],
) as dag:
    load_reviews_task = PythonOperator(
        task_id="load_reviews",
        python_callable=load_reviews,
    )

    clean_reviews_task = PythonOperator(
        task_id="clean_reviews",
        python_callable=clean_reviews,
    )

    create_interactions_task = PythonOperator(
        task_id="create_interactions",
        python_callable=create_interactions,
    )

    validate_outputs_task = PythonOperator(
        task_id="validate_review_outputs",
        python_callable=validate_review_outputs,
    )

    load_to_mariadb_task = PythonOperator(
        task_id="load_reviews_to_mariadb",
        python_callable=load_reviews_to_mariadb,
    )

    (
        load_reviews_task
        >> clean_reviews_task
        >> create_interactions_task
        >> validate_outputs_task
        >> load_to_mariadb_task
    )

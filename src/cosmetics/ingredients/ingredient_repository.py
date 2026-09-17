from pathlib import Path
import logging
import os
import re
import pandas as pd
import pymysql
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / '.env'
load_dotenv(ENV_PATH)

logger = logging.getLogger(__name__)
DB_HOST = os.getenv('DB_HOST')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')


def clean_ingredient_name(name):
    name = str(name).strip()
    name = re.sub('\\s+', ' ', name)
    return name


def normalize_ingredient_key(name):
    name = clean_ingredient_name(name)
    name = name.casefold()
    name = re.sub('\\s+', '', name)
    return name


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )

# dataset_metadata의 최신 리뷰 작성일(submission_time)을 사용한다.


def get_latest_review_date():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("\n                SHOW TABLES\n                LIKE 'dataset_metadata'\n                ")
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                '\n                SELECT metadata_value\n                FROM dataset_metadata\n                WHERE metadata_key = %s\n                LIMIT 1\n                ',
                ('sephora_reviews_latest_date',),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return row.get('metadata_value')
    finally:
        conn.close()


def resolve_ingredient(ingredient_name):
    search_key = normalize_ingredient_key(ingredient_name)
    if not search_key:
        return None
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '\n                SELECT\n                    ingredient_key,\n                    ingredient_en,\n                    ingredient_kr,\n                    synonym,\n                    regulate_type,\n                    limit_condition,\n                    matched,\n                    recommendable,\n                    needs_review\n                FROM ingredients\n                WHERE ingredient_key = %s\n                LIMIT 1\n                ',
                (search_key,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    'ingredient_key': row['ingredient_key'],
                    'ingredient_en': row['ingredient_en'],
                    'ingredient_kr': row.get('ingredient_kr'),
                    'match_type': 'ingredient_key',
                }
            cursor.execute('\n                SELECT\n                    ingredient_key,\n                    ingredient_en,\n                    ingredient_kr,\n                    synonym\n                FROM ingredients\n                ')
            rows = cursor.fetchall()
        for row in rows:
            ingredient_en = row.get('ingredient_en')
            if ingredient_en is None:
                continue
            key = normalize_ingredient_key(ingredient_en)
            if key == search_key:
                return {
                    'ingredient_key': row['ingredient_key'],
                    'ingredient_en': row['ingredient_en'],
                    'ingredient_kr': row.get('ingredient_kr'),
                    'match_type': 'ingredient_en',
                }
        for row in rows:
            ingredient_kr = row.get('ingredient_kr')
            if ingredient_kr is None:
                continue
            key = normalize_ingredient_key(ingredient_kr)
            if key == search_key:
                return {
                    'ingredient_key': row['ingredient_key'],
                    'ingredient_en': row['ingredient_en'],
                    'ingredient_kr': row.get('ingredient_kr'),
                    'match_type': 'mfds_korean',
                }
        for row in rows:
            synonym = row.get('synonym')
            if synonym is None:
                continue
            synonyms = re.split(',|;|\\|', str(synonym))
            for item in synonyms:
                synonym_key = normalize_ingredient_key(item)
                if synonym_key == search_key:
                    return {
                        'ingredient_key': row['ingredient_key'],
                        'ingredient_en': row['ingredient_en'],
                        'ingredient_kr': row.get('ingredient_kr'),
                        'match_type': 'mfds_synonym',
                    }
        return None
    finally:
        conn.close()


SKIN_CONCERN_PRIORITY = [
    'sensitivity',
    'redness',
    'barrier',
    'dryness',
    'blackheads',
    'acne',
    'pores',
    'sebum',
    'pigmentation',
    'dullness',
    'wrinkles',
    'elasticity',
    'texture',
]


AUTO_INGREDIENT_BY_CONCERN = {
    'pores': ['나이아신아마이드'],
    'sebum': ['나이아신아마이드'],
    'blackheads': ['살리실산', '나이아신아마이드'],
    'acne': ['살리실산', '나이아신아마이드'],
    'dryness': ['히알루론산', '판테놀'],
    'sensitivity': ['판테놀', '세라마이드', '병풀'],
    'redness': ['병풀', '판테놀', '세라마이드'],
    'barrier': ['세라마이드', '판테놀'],
    'dullness': ['비타민 C', '나이아신아마이드'],
    'pigmentation': ['나이아신아마이드', '비타민 C'],
    'wrinkles': ['펩타이드', '레티놀'],
    'elasticity': ['펩타이드'],
    'texture': ['젖산', '글리콜산'],
}


AUTO_INGREDIENT_BY_SKIN_TYPE = {
    'oily': ['나이아신아마이드'],
    'dry': ['히알루론산', '판테놀'],
    'combination': ['나이아신아마이드'],
    'sensitive': ['판테놀', '세라마이드'],
    'normal': ['히알루론산', '나이아신아마이드'],
}


SKIN_CONCERN_KR = {
    'pores': '모공',
    'sebum': '피지·유분',
    'blackheads': '블랙헤드',
    'acne': '트러블',
    'dryness': '건조·당김',
    'sensitivity': '민감·자극',
    'redness': '홍조·붉은기',
    'barrier': '피부 장벽',
    'dullness': '칙칙함',
    'pigmentation': '잡티·색소',
    'wrinkles': '주름',
    'elasticity': '탄력',
    'texture': '각질·피부결',
}


SKIN_TYPE_KR = {
    'oily': '지성',
    'dry': '건성',
    'combination': '복합성',
    'sensitive': '민감성',
    'normal': '중성',
}


def _first_resolvable_ingredient(candidates):
    for ingredient_name in candidates:
        if resolve_ingredient(ingredient_name) is not None:
            return ingredient_name
    return None


def get_auto_ingredient_candidates(skin_type='unknown', skin_concerns=None):
    skin_concerns = [str(value).strip() for value in skin_concerns or [] if str(value).strip()]
    candidates = []
    seen = set()

    def add_candidates(names, source, basis, basis_label):
        for name in names:
            ingredient_name = str(name).strip()
            if not ingredient_name:
                continue
            key = normalize_ingredient_key(ingredient_name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({'ingredient_name': ingredient_name, 'source': source, 'basis': basis, 'basis_label': basis_label})
    for concern in SKIN_CONCERN_PRIORITY:
        if concern not in skin_concerns:
            continue
        add_candidates(
            names=AUTO_INGREDIENT_BY_CONCERN.get(concern, []),
            source='skin_concern',
            basis=concern,
            basis_label=SKIN_CONCERN_KR.get(concern, concern),
        )
    normalized_skin_type = str(skin_type or '').strip().casefold()
    if normalized_skin_type in AUTO_INGREDIENT_BY_SKIN_TYPE:
        add_candidates(
            names=AUTO_INGREDIENT_BY_SKIN_TYPE.get(normalized_skin_type, []),
            source='skin_type',
            basis=normalized_skin_type,
            basis_label=SKIN_TYPE_KR.get(normalized_skin_type, normalized_skin_type),
        )
    return candidates


def build_ingredient_selection(
    candidate,
    *,
    model_available=None,
    fallback_to_web=False,
    attempt_index=0,
):
    if not candidate:
        return None
    selection = dict(candidate)
    label = selection.get('basis_label')
    ingredient_name = selection.get('ingredient_name')
    if model_available is True:
        if attempt_index > 0:
            reason = f'{label} 기준 성분 후보를 순서대로 확인한 뒤, 현재 개인화 모델에서 추천 가능한 {ingredient_name}을 우선 탐색 성분으로 선택했습니다.'
        else:
            reason = f'{label}을 기준으로 {ingredient_name}을 우선 탐색 성분으로 선택했습니다.'
    elif fallback_to_web:
        reason = f'{label}을 기준으로 {ingredient_name}을 우선 탐색 성분으로 확인했지만, 현재 개인화 모델에서 조건에 맞는 추천 상품을 만들지 못해 최근 웹 언급을 참고 정보로 확인합니다.'
    else:
        reason = f'{label}을 기준으로 {ingredient_name}을 우선 탐색 성분으로 선택했습니다.'
    selection['model_available'] = model_available
    selection['fallback_to_web'] = bool(fallback_to_web)
    selection['reason'] = reason
    return selection


def select_auto_ingredient(skin_type='unknown', skin_concerns=None):
    candidates = get_auto_ingredient_candidates(
        skin_type=skin_type,
        skin_concerns=skin_concerns,
    )
    if not candidates:
        return None
    return build_ingredient_selection(candidates[0])


PRODUCT_TYPE_KEYWORDS = {
    '세럼': ['세럼', 'serum', 'serums'],
    '앰플': ['앰플', 'ampoule', 'ampoules'],
    '토너': ['토너', 'toner', 'toners'],
    '크림': ['크림', 'cream', 'creams', 'moisturizer', 'moisturizers'],
    '로션': ['로션', 'lotion', 'lotions', 'moisturizer', 'moisturizers'],
    '에센스': ['에센스', 'essence', 'essences'],
    '클렌저': ['클렌저', 'cleanser', 'cleansers', 'cleansing'],
    '선크림': ['선크림', 'sunscreen', 'sunscreens', 'spf'],
    '파운데이션': ['파운데이션', 'foundation', 'foundations'],
    '쿠션': ['쿠션', 'cushion'],
    '프라이머': ['프라이머', 'primer', 'primers'],
    '컨실러': ['컨실러', 'concealer', 'concealers'],
    '립스틱': ['립스틱', 'lipstick', 'lipsticks'],
    '틴트': ['틴트', 'tint', 'lip stain', 'stain'],
    '아이섀도': ['아이섀도', 'eyeshadow', 'eye shadow', 'eye palette'],
    '아이라이너': ['아이라이너', 'eyeliner', 'eye liner'],
    '마스카라': ['마스카라', 'mascara'],
}


def normalize_product_type(product_type):
    if product_type is None:
        return None
    value = str(product_type).strip()
    if not value:
        return None
    return value


def _get_product_columns(cursor):
    cursor.execute('SHOW COLUMNS FROM products')
    return {row['Field'] for row in cursor.fetchall()}


def filter_products_by_product_type(products, product_type):
    product_type = normalize_product_type(product_type)
    if product_type is None or products.empty:
        return products
    keywords = PRODUCT_TYPE_KEYWORDS.get(product_type, [product_type])
    text_columns = [column for column in ['product_name', 'primary_category', 'secondary_category', 'tertiary_category'] if column in products.columns]
    if not text_columns:
        return products.iloc[0:0].copy()
    combined = products[text_columns].fillna('').astype(str).agg(' '.join, axis=1).str.casefold()
    mask = pd.Series(False, index=products.index)
    for keyword in keywords:
        keyword = str(keyword).strip().casefold()
        if not keyword:
            continue
        mask = mask | combined.str.contains(re.escape(keyword), regex=True, na=False)
    return products[mask].copy().reset_index(drop=True)


def find_products_by_product_type(product_type, limit=None):
    product_type = normalize_product_type(product_type)
    if not product_type:
        return pd.DataFrame()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            product_columns = _get_product_columns(cursor)
            select_columns = ['p.product_id', 'p.product_name']
            optional_columns = [
                'brand_name',
                'price_usd',
                'rating',
                'reviews',
                'latest_review_date',
                'loves_count',
                'product_url',
                'primary_category',
                'secondary_category',
                'tertiary_category',
            ]
            for column in optional_columns:
                if column in product_columns:
                    select_columns.append(f'p.{column}')
            sql = f"\n                SELECT\n                    {', '.join(select_columns)}\n                FROM products p\n                ORDER BY p.product_id\n            "
            cursor.execute(sql)
            rows = cursor.fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame()
    products = pd.DataFrame(rows)
    products = filter_products_by_product_type(products=products, product_type=product_type)
    if limit is not None:
        products = products.head(int(limit)).copy()
    return products


PERFORMANCE_TREND_KEYWORD_PREFIX = {
    'pore_cover': '모공 커버',
    'coverage': '커버력',
    'blur': '블러',
    'longevity': '지속력',
    'adhesion': '밀착력',
    'color_payoff': '발색',
    'dewy_finish': '윤광',
    'matte_finish': '매트',
}


def build_performance_trend_keyword(performance_goal, product_type):
    product_type = str(product_type or '').strip()
    prefix = PERFORMANCE_TREND_KEYWORD_PREFIX.get(str(performance_goal or '').strip())
    if prefix and product_type:
        return f'{prefix} {product_type}'
    if prefix:
        return prefix
    return product_type


def has_trend_signal(summary):
    if not isinstance(summary, dict):
        return False
    explicit_signal = summary.get('has_recent_signal')
    if explicit_signal is not None:
        return bool(explicit_signal)
    try:
        recent_average = float(summary.get('recent_average') or 0)
        previous_average = float(summary.get('previous_average') or 0)
    except (TypeError, ValueError):
        return False
    return recent_average > 0 or previous_average > 0

# LightFM 결과가 비어 있을 때 DB 후보를 Bayesian rating으로 정렬한다.


def build_catalog_fallback_recommendations(products, top_n=10):
    if products is None or products.empty:
        return []
    ranked = products.copy()
    if 'rating' not in ranked.columns:
        ranked['rating'] = None
    if 'reviews' not in ranked.columns:
        ranked['reviews'] = 0
    ranked['rating_num'] = pd.to_numeric(ranked['rating'], errors='coerce')
    ranked['reviews_num'] = pd.to_numeric(ranked['reviews'], errors='coerce').fillna(0)
    valid_ratings = ranked['rating_num'].dropna()
    if valid_ratings.empty:
        ranked = ranked.sort_values(
            by=['reviews_num', 'product_id'],
            ascending=[False, True],
            kind='mergesort',
        )
    else:
        candidate_mean = float(valid_ratings.mean())
        positive_reviews = ranked.loc[ranked['reviews_num'] > 0, 'reviews_num']
        if positive_reviews.empty:
            min_reviews = 1.0
        else:
            min_reviews = float(positive_reviews.quantile(0.6))
            if min_reviews <= 0:
                min_reviews = 1.0
        rating_value = ranked['rating_num'].fillna(candidate_mean)
        review_count = ranked['reviews_num'].clip(lower=0)
        ranked['_fallback_score'] = review_count / (review_count + min_reviews) * rating_value + min_reviews / (review_count + min_reviews) * candidate_mean
        sort_columns = ['_fallback_score', 'reviews_num']
        ascending = [False, False]
        if 'loves_count' in ranked.columns:
            ranked['_loves_num'] = pd.to_numeric(ranked['loves_count'], errors='coerce').fillna(0)
            sort_columns.append('_loves_num')
            ascending.append(False)
        sort_columns.append('product_id')
        ascending.append(True)
        ranked = ranked.sort_values(by=sort_columns, ascending=ascending, kind='mergesort')
    keep_columns = [column for column in ['product_id', 'product_name', 'brand_name', 'rating', 'reviews', 'price_usd', 'latest_review_date', 'product_url'] if column in ranked.columns]
    ranked = ranked[keep_columns].head(int(top_n)).copy()
    ranked = ranked.astype(object).where(pd.notna(ranked), None)
    return ranked.to_dict(orient='records')


def recommend_products_by_type(
    product_type,
    performance_goal=None,
    skin_type='unknown',
    skin_tone='unknown',
    eye_color='unknown',
    hair_color='unknown',
    skin_concerns=None,
    top_n=10,
    allow_catalog_fallback=True,
):
    from src.recommendation.sephora_lightfm import recommend_new_user_from_candidates
    from src.cosmetics.trends.google_trends_collector import collect_keyword_trend, summarize_keyword_trend
    from src.cosmetics.trends.product_trend_collector import get_web_product_recommendations

    products = find_products_by_product_type(product_type=product_type, limit=None)
    candidate_count = 0 if products is None or products.empty else len(products)
    recommendation_list = []
    web_recommendations = []
    if candidate_count > 0:
        candidate_product_ids = products['product_id'].astype(str).tolist()
        recommendations = recommend_new_user_from_candidates(
            candidate_product_ids=candidate_product_ids,
            skin_type=skin_type,
            skin_tone=skin_tone,
            eye_color=eye_color,
            hair_color=hair_color,
            top_n=top_n,
        )
        recommendation_df = pd.DataFrame(recommendations)
        if not recommendation_df.empty:
            product_columns = [column for column in ['product_id', 'product_name', 'brand_name', 'rating', 'reviews', 'price_usd', 'latest_review_date', 'product_url'] if column in products.columns]
            product_info = products[product_columns].copy()
            product_info['product_id'] = product_info['product_id'].astype(str)
            recommendation_df['product_id'] = recommendation_df['product_id'].astype(str)
            result_df = recommendation_df.merge(product_info, on='product_id', how='left')
            result_df = result_df.astype(object).where(pd.notna(result_df), None)
            recommendation_list = result_df.to_dict(orient='records')
    if recommendation_list:
        recommendation_status = 'personalized_recommendation_available'
        ranking_method = 'lightfm'
        recommendation_note = 'LightFM 개인화 모델이 후보 상품의 순위를 계산했습니다.'
    elif candidate_count > 0 and allow_catalog_fallback:
        recommendation_list = build_catalog_fallback_recommendations(
            products=products,
            top_n=top_n,
        )
        if recommendation_list:
            recommendation_status = 'fallback_recommendation_available'
            ranking_method = 'catalog_bayesian_fallback'
            recommendation_note = 'LightFM 학습 범위에서 추천 가능한 상품이 없어 같은 데이터셋 후보군에서 평점과 리뷰 수를 함께 고려한 대체 순위를 제공합니다.'
        else:
            recommendation_status = 'model_products_unavailable'
            ranking_method = 'none'
            recommendation_note = None
    elif candidate_count > 0:
        recommendation_status = 'model_products_unavailable'
        ranking_method = 'none'
        recommendation_note = None
    else:
        recommendation_status = 'model_candidates_unavailable'
        ranking_method = 'none'
        recommendation_note = None
    requested_trend_keyword = build_performance_trend_keyword(
        performance_goal=performance_goal,
        product_type=product_type,
    )
    trend_keyword = requested_trend_keyword or str(product_type or '').strip()
    web_search_query = trend_keyword or str(product_type or '').strip()
    web_search_status = 'not_needed'
    if candidate_count == 0 and web_search_query:
        try:
            web_recommendations = get_web_product_recommendations(
                search_query=web_search_query,
                product_type=product_type,
                top_n=min(int(top_n), 5),
                geo='KR',
            )
            if web_recommendations:
                recommendation_status = 'web_fallback_available'
                ranking_method = 'gemini_google_search'
                recommendation_note = '데이터셋에 현재 조건과 일치하는 상품이 없어 Gemini + Google Search로 외부 제품을 실시간 탐색했습니다. 데이터셋 기반 개인화 순위는 아닙니다.'
                web_search_status = 'available'
            else:
                web_search_status = 'empty'
        except Exception as exc:
            logger.warning('Gemini web product search failed: %s', exc)
            web_recommendations = []
            web_search_status = 'unavailable'
    trend_summary = None
    trend_status = 'unavailable'
    trend_candidates = []
    for keyword in [requested_trend_keyword, product_type]:
        keyword = str(keyword or '').strip()
        if keyword and keyword not in trend_candidates:
            trend_candidates.append(keyword)
    for keyword in trend_candidates:
        try:
            trend_rows = collect_keyword_trend(
                keyword=keyword,
                geo='KR',
                timeframe='today 12-m',
            )
            summary = summarize_keyword_trend(trend_rows)
            if has_trend_signal(summary):
                trend_summary = summary
                trend_keyword = keyword
                trend_status = 'available'
                break
        except Exception:
            continue
    return {
        'ingredient': None,
        'ingredient_query': None,
        'ingredient_selection': None,
        'recommendation_mode': 'product_performance',
        'performance_goal': performance_goal,
        'performance_data_available': False,
        'performance_note': '현재 데이터에는 커버력, 블러, 지속력, 밀착력, 발색 같은 직접 성능 측정값이 없습니다. 데이터셋 후보가 있으면 후보군 안에서 추천하고, 후보 자체가 없으면 웹 검색 결과를 별도로 제공합니다.',
        'product_type': product_type,
        'candidate_count': candidate_count,
        'recommendation_status': recommendation_status,
        'ranking_method': ranking_method,
        'recommendation_note': recommendation_note,
        'user_profile': {
            'product_type': product_type,
            'skin_type': skin_type,
            'skin_tone': skin_tone,
            'eye_color': eye_color,
            'hair_color': hair_color,
            'skin_concerns': skin_concerns or [],
        },
        'trend': trend_summary,
        'trend_status': trend_status,
        'trend_keyword': trend_keyword,
        'trend_subject_type': 'product_keyword',
        'trend_geo': 'KR',
        'trend_timeframe': 'today 12-m',
        'recommendations': recommendation_list,
        'web_recommendations': web_recommendations,
        'web_search_query': web_search_query,
        'web_search_status': web_search_status,
        'trending_products': [],
        'web_trend_status': 'not_applicable',
        'trend_period_days': None,
    }


def find_products_by_ingredient(ingredient_name, product_type=None, limit=None):
    ingredient = resolve_ingredient(ingredient_name)
    if ingredient is None:
        return (None, pd.DataFrame())
    ingredient_key = ingredient['ingredient_key']
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            product_columns = _get_product_columns(cursor)
            select_columns = ['p.product_id', 'p.product_name']
            optional_columns = [
                'brand_name',
                'price_usd',
                'rating',
                'reviews',
                'latest_review_date',
                'loves_count',
                'product_url',
                'primary_category',
                'secondary_category',
                'tertiary_category',
            ]
            for column in optional_columns:
                if column in product_columns:
                    select_columns.append(f'p.{column}')
            sql = f"\n                SELECT\n                    {', '.join(select_columns)}\n                FROM products p\n                INNER JOIN product_ingredients pi\n                    ON p.product_id = pi.product_id\n                WHERE pi.ingredient_key = %s\n                ORDER BY p.product_id\n            "
            cursor.execute(sql, (ingredient_key,))
            rows = cursor.fetchall()
    finally:
        conn.close()
    if not rows:
        return (ingredient, pd.DataFrame())
    products = pd.DataFrame(rows)
    products = filter_products_by_product_type(products=products, product_type=product_type)
    if limit is not None:
        products = products.head(int(limit)).copy()
    return (ingredient, products)


def recommend_cosmetics(
    ingredient_name,
    product_type=None,
    skin_type='unknown',
    skin_tone='unknown',
    eye_color='unknown',
    hair_color='unknown',
    skin_concerns=None,
    top_n=10,
    trend_top_n=3,
    ingredient_selection=None,
    collect_trends=True,
    allow_catalog_fallback=True,
):
    del trend_top_n
    from src.recommendation.sephora_lightfm import recommend_new_user_from_candidates
    from src.cosmetics.trends.google_trends_collector import collect_keyword_trend, summarize_keyword_trend
    from src.cosmetics.trends.product_trend_collector import get_web_product_recommendations

    ingredient_name = str(ingredient_name or '').strip()
    ingredient, products = find_products_by_ingredient(
        ingredient_name=ingredient_name,
        product_type=product_type,
        limit=None,
    )

    candidate_count = 0 if products is None or products.empty else len(products)

    recommendation_list = []

    web_recommendations = []


    if candidate_count > 0:
        candidate_product_ids = products['product_id'].astype(str).tolist()
        recommendations = recommend_new_user_from_candidates(
            candidate_product_ids=candidate_product_ids,
            skin_type=skin_type,
            skin_tone=skin_tone,
            eye_color=eye_color,
            hair_color=hair_color,
            top_n=top_n,
        )

        recommendation_df = pd.DataFrame(recommendations)

        if not recommendation_df.empty:
            product_columns = [column for column in ['product_id', 'product_name', 'brand_name', 'rating', 'reviews', 'price_usd', 'latest_review_date', 'product_url'] if column in products.columns]
            product_info = products[product_columns].copy()
            product_info['product_id'] = product_info['product_id'].astype(str)
            recommendation_df['product_id'] = recommendation_df['product_id'].astype(str)
            result_df = recommendation_df.merge(product_info, on='product_id', how='left')
            result_df = result_df.astype(object).where(pd.notna(result_df), None)
            recommendation_list = result_df.to_dict(orient='records')

    if recommendation_list:
        recommendation_status = 'personalized_recommendation_available'
        ranking_method = 'lightfm'
        recommendation_note = 'LightFM 개인화 모델이 후보 상품의 순위를 계산했습니다.'

    elif candidate_count > 0 and allow_catalog_fallback:
        recommendation_list = build_catalog_fallback_recommendations(
            products=products,
            top_n=top_n,
        )

        if recommendation_list:
            recommendation_status = 'fallback_recommendation_available'
            ranking_method = 'catalog_bayesian_fallback'
            recommendation_note = 'LightFM 학습 범위에서 추천 가능한 상품이 없어 같은 데이터셋 후보군에서 평점과 리뷰 수를 함께 고려한 대체 순위를 제공합니다.'
        
        else:
            recommendation_status = 'model_products_unavailable'
            ranking_method = 'none'
            recommendation_note = None
    
    elif candidate_count > 0:
        recommendation_status = 'model_products_unavailable'
        ranking_method = 'none'
        recommendation_note = None
    
    else:
        recommendation_status = 'model_candidates_unavailable'
        ranking_method = 'none'
        recommendation_note = None

    trend_keyword = ingredient_name
    trend_summary = None

    if collect_trends and trend_keyword:

        try:
            trend_rows = collect_keyword_trend(
                keyword=trend_keyword,
                geo='KR',
                timeframe='today 12-m',
            )
            trend_candidate = summarize_keyword_trend(trend_rows)

            if has_trend_signal(trend_candidate):
                trend_summary = trend_candidate

            else:
                trend_summary = None

        except Exception:
            trend_summary = None

    web_search_query = ' '.join((part for part in [ingredient_name, str(product_type or '').strip()] if part)).strip()
    web_search_status = 'not_needed'

    
    if collect_trends and candidate_count == 0 and web_search_query:

        try:
            web_recommendations = get_web_product_recommendations(
                search_query=web_search_query,
                product_type=product_type,
                top_n=min(int(top_n), 5),
                geo='KR',
            )

            if web_recommendations:
                recommendation_status = 'web_fallback_available'
                ranking_method = 'gemini_google_search'
                recommendation_note = '데이터셋에 현재 조건과 일치하는 상품이 없어 Gemini + Google Search로 외부 제품을 실시간 탐색했습니다. 데이터셋 기반 개인화 순위는 아닙니다.'
                web_search_status = 'available'

            else:
                web_search_status = 'empty'

        except Exception as exc:
            logger.warning('Gemini web product search failed: %s', exc)
            web_recommendations = []
            web_search_status = 'unavailable'
    
    return {
        'ingredient': ingredient,
        'ingredient_query': trend_keyword,
        'product_type': product_type,
        'candidate_count': candidate_count,
        'recommendation_status': recommendation_status,
        'ranking_method': ranking_method,
        'recommendation_note': recommendation_note,
        'user_profile': {
            'product_type': product_type,
            'skin_type': skin_type,
            'skin_tone': skin_tone,
            'eye_color': eye_color,
            'hair_color': hair_color,
            'skin_concerns': skin_concerns or [],
        },
        'ingredient_selection': ingredient_selection,
        'trend': trend_summary,
        'trend_status': 'available' if trend_summary is not None else 'unavailable',
        'trend_keyword': trend_keyword,
        'trend_subject_type': 'ingredient',
        'trend_geo': 'KR',
        'trend_timeframe': 'today 12-m',
        'recommendations': recommendation_list,
        'web_recommendations': web_recommendations,
        'web_search_query': web_search_query,
        'web_search_status': web_search_status,
        'trending_products': [],
        'web_trend_status': 'not_applicable',
        'trend_period_days': None,
    }

# 자연어 파싱 결과에 따라 추천 경로를 결정한다.


def recommend_from_user_query(user_text, top_n=10, trend_top_n=3):
    
    from src.cosmetics.query.user_query_parser import parse_user_query

    parsed = parse_user_query(user_text)
    missing_fields = list(parsed.get('missing_fields', []) or [])
    user_ingredient = parsed.get('ingredient')
    user_specified_ingredient = bool(str(user_ingredient or '').strip())
    product_type = parsed.get('product_type')
    recommendation_mode = parsed.get('recommendation_mode') or 'skincare'
    performance_goal = parsed.get('performance_goal')
    auto_candidates = []
    ingredient_selection = None
    
    if not user_specified_ingredient and recommendation_mode == 'skincare':
        auto_candidates = get_auto_ingredient_candidates(
            skin_type=parsed.get('skin_type') or 'unknown',
            skin_concerns=parsed.get('skin_concerns') or [],
        )
        
        if auto_candidates:
            ingredient_selection = build_ingredient_selection(auto_candidates[0])
            parsed['auto_selected_ingredient'] = auto_candidates[0]['ingredient_name']
            parsed['ingredient_selection'] = ingredient_selection
            missing_fields = [field for field in missing_fields if field != 'ingredient']
        
        elif 'ingredient' not in missing_fields:
            missing_fields.append('ingredient')
    
    if recommendation_mode == 'product_performance':
        missing_fields = [field for field in missing_fields if field != 'ingredient']
    
    if not product_type:
        if 'product_type' not in missing_fields:
            missing_fields.append('product_type')
    
    parsed['missing_fields'] = missing_fields
    
    if missing_fields:
        return {
            'status': 'need_more_info',
            'missing_fields': missing_fields,
            'parsed_query': parsed,
            'ingredient_selection': ingredient_selection,
            'auto_ingredient_candidates': auto_candidates,
            'message': '추천에 필요한 추가 정보가 있습니다.',
            'recommendations': [],
            'trending_products': [],
        }
    
    common_kwargs = {
        'product_type': product_type,
        'skin_type': parsed.get('skin_type') or 'unknown',
        'skin_tone': parsed.get('skin_tone') or 'unknown',
        'eye_color': parsed.get('eye_color') or 'unknown',
        'hair_color': parsed.get('hair_color') or 'unknown',
        'skin_concerns': parsed.get('skin_concerns') or [],
        'top_n': top_n,
        'trend_top_n': trend_top_n,
    }
    
    if recommendation_mode == 'product_performance' and (not user_specified_ingredient):
        result = recommend_products_by_type(
            product_type=product_type,
            performance_goal=performance_goal,
            skin_type=parsed.get('skin_type') or 'unknown',
            skin_tone=parsed.get('skin_tone') or 'unknown',
            eye_color=parsed.get('eye_color') or 'unknown',
            hair_color=parsed.get('hair_color') or 'unknown',
            skin_concerns=parsed.get('skin_concerns') or [],
            top_n=top_n,
        )
        return {
            'status': 'ok',
            'ingredient_source': 'not_used',
            'auto_ingredient_attempts': [],
            'parsed_query': parsed,
            **result,
        }
    
    if user_specified_ingredient:
        result = recommend_cosmetics(
            ingredient_name=str(user_ingredient).strip(),
            ingredient_selection=None,
            collect_trends=True,
            **common_kwargs,
        )
        return {
            'status': 'ok',
            'ingredient_source': 'user',
            'auto_ingredient_attempts': [],
            'parsed_query': parsed,
            **result,
        }
    
    attempts = []
    selected_candidate = None
    
    for index, candidate in enumerate(auto_candidates):
        probe_selection = build_ingredient_selection(candidate, attempt_index=index)
        probe = recommend_cosmetics(
            ingredient_name=candidate['ingredient_name'],
            ingredient_selection=probe_selection,
            collect_trends=False,
            allow_catalog_fallback=False,
            **common_kwargs,
        )
        attempt = {
            'ingredient_name': candidate['ingredient_name'],
            'source': candidate.get('source'),
            'basis': candidate.get('basis'),
            'basis_label': candidate.get('basis_label'),
            'candidate_count': probe.get('candidate_count', 0),
            'recommendation_count': len(probe.get('recommendations', []) or []),
            'recommendation_status': probe.get('recommendation_status'),
        }
        attempts.append(attempt)
    
        if probe.get('recommendation_status') == 'personalized_recommendation_available':
            selected_candidate = (candidate, index)
            break
    
    if selected_candidate:
        candidate, index = selected_candidate
        ingredient_selection = build_ingredient_selection(
            candidate,
            model_available=True,
            attempt_index=index,
        )
        ingredient_name = candidate['ingredient_name']
        parsed['auto_selected_ingredient'] = ingredient_name
        parsed['ingredient_selection'] = ingredient_selection
        result = recommend_cosmetics(
            ingredient_name=ingredient_name,
            ingredient_selection=ingredient_selection,
            collect_trends=True,
            **common_kwargs,
        )
    
        return {
            'status': 'ok',
            'ingredient_source': 'auto',
            'auto_ingredient_attempts': attempts,
            'parsed_query': parsed,
            **result,
        }
    
    fallback_candidate = None
    
    for attempt, candidate in zip(attempts, auto_candidates):
        if attempt.get('candidate_count', 0) > 0:
            fallback_candidate = candidate
            break
    if fallback_candidate is None and auto_candidates:
        fallback_candidate = auto_candidates[0]

    if fallback_candidate is None:
        return {
            'status': 'need_more_info',
            'missing_fields': ['ingredient'],
            'parsed_query': parsed,
            'ingredient_selection': None,
            'auto_ingredient_attempts': attempts,
            'message': '추천을 위해 성분 또는 피부 타입/고민 정보가 필요합니다.',
            'recommendations': [],
            'trending_products': [],
        }
    
    ingredient_selection = build_ingredient_selection(
        fallback_candidate,
        model_available=False,
        fallback_to_web=True,
        attempt_index=0,
    )
    ingredient_name = fallback_candidate['ingredient_name']
    parsed['auto_selected_ingredient'] = ingredient_name
    parsed['ingredient_selection'] = ingredient_selection
    result = recommend_cosmetics(
        ingredient_name=ingredient_name,
        ingredient_selection=ingredient_selection,
        collect_trends=True,
        **common_kwargs,
    )
    
    return {
        'status': 'ok',
        'ingredient_source': 'auto',
        'auto_ingredient_attempts': attempts,
        'parsed_query': parsed,
        **result,
    }


if __name__ == '__main__':
    import json
    user_text = input('화장품 추천 질문을 입력하세요: ').strip()
    result = recommend_from_user_query(user_text=user_text, top_n=5, trend_top_n=3)
    print()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

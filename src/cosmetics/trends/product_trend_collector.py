import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite",)

DEFAULT_GEO = os.getenv("PRODUCT_TREND_GEO", "KR",)
DEFAULT_TOP_N = int(os.getenv("PRODUCT_TREND_TOP_N", "5",))


class WebProductItem(BaseModel):
    brand_name: str
    product_name: str
    reason: str
    source_url: str


class WebProductSearchResponse(BaseModel):
    products: list[WebProductItem]


def validate_config():
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY가 .env에 없습니다."
        )


def geo_to_market(geo):
    markets = {
        "KR": "대한민국",
        "US": "미국",
        "JP": "일본",
        "GB": "영국",
        "CA": "캐나다",
        "AU": "호주",
    }

    code = str(
        geo or ""
    ).upper()

    return markets.get(
        code,
        code,
    )


def extract_grounding_urls(response):
    urls = []
    seen = set()

    candidates = getattr(
        response,
        "candidates",
        None,
    ) or []

    if not candidates:
        return urls

    metadata = getattr(
        candidates[0],
        "grounding_metadata",
        None,
    )

    if metadata is None:
        return urls

    chunks = getattr(
        metadata,
        "grounding_chunks",
        None,
    ) or []

    for chunk in chunks:
        web = getattr(
            chunk,
            "web",
            None,
        )

        if web is None:
            continue

        uri = str(
            getattr(
                web,
                "uri",
                "",
            )
            or ""
        ).strip()

        if not uri or uri in seen:
            continue

        seen.add(uri)
        urls.append(uri)

    return urls


def build_web_product_prompt(
    search_query,
    product_type=None,
    top_n=5,
    geo="KR",
):
    market = geo_to_market(geo)
    product_type_text = (
        str(product_type).strip()
        if product_type
        else "화장품"
    )

    return f"""
Google Search를 사용해 현재 {market}에서
다음 요청과 직접 관련된 실제 화장품을 찾아라.

사용자 검색 의도:
- {search_query}

제품 유형:
- {product_type_text}

조건:
1. 실제로 존재하는 브랜드명과 제품명만 반환한다.
2. 제품 유형이 지정되어 있다면 반드시 그 유형과 맞아야 한다.
3. 사용자 검색 의도와 직접 관련된 근거가 검색 결과에 있어야 한다.
4. 공식 브랜드, 국내/글로벌 리테일러, 뷰티 기사,
   신뢰할 수 있는 리뷰나 랭킹 등 확인 가능한 웹 근거를 우선한다.
5. 제품명만 보고 효능이나 성능을 추측하지 않는다.
6. 가격, 판매량, 검색량, 평점, 리뷰 수를 추정하지 않는다.
7. reason에는 검색 의도와 관련 있다고 판단한 이유를
   검색 근거 범위 안에서 한 문장으로 작성한다.
8. source_url에는 대표 근거 URL 1개를 넣는다.
9. 조건에 맞는 제품이 없으면 products를 빈 배열로 반환한다.
10. 최대 {int(top_n)}개만 반환한다.

지정된 JSON 구조만 반환한다.
""".strip()


def normalize_products(
    payload,
    top_n,
    grounding_urls=None,
    search_query=None,
):
    grounding_urls = grounding_urls or []
    raw_products = (
        payload.get("products", [])
        or []
    )

    results = []
    seen = set()

    for item in raw_products:
        brand_name = str(
            item.get("brand_name", "")
            or ""
        ).strip()

        product_name = str(
            item.get("product_name", "")
            or ""
        ).strip()

        reason = str(
            item.get("reason", "")
            or ""
        ).strip()

        source_url = str(
            item.get("source_url", "")
            or ""
        ).strip()

        if not product_name:
            continue

        key = (
            f"{brand_name}|{product_name}"
            .casefold()
        )

        if key in seen:
            continue

        seen.add(key)

        if (
            not source_url
            and grounding_urls
        ):
            url_index = min(
                len(results),
                len(grounding_urls) - 1,
            )
            source_url = (
                grounding_urls[url_index]
            )

        results.append(
            {
                "rank": len(results) + 1,
                "brand_name": brand_name,
                "product_name": product_name,
                "reason": reason,
                "source_url": source_url,
                "search_query": search_query,
            }
        )

        if len(results) >= int(top_n):
            break

    return results


def get_web_product_recommendations(
    search_query,
    product_type=None,
    top_n=DEFAULT_TOP_N,
    geo=DEFAULT_GEO,
):
    validate_config()

    search_query = str(
        search_query or ""
    ).strip()

    product_type = str(
        product_type or ""
    ).strip()

    if not search_query:
        return []

    top_n = max(
        1,
        min(
            int(top_n),
            10,
        ),
    )

    prompt = build_web_product_prompt(
        search_query=search_query,
        product_type=(
            product_type
            or None
        ),
        top_n=top_n,
        geo=geo,
    )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    started = time.perf_counter()

    try:
        response = (
            client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            google_search=(
                                types.GoogleSearch()
                            )
                        )
                    ],
                    thinking_config=(
                        types.ThinkingConfig(
                            thinking_level="minimal"
                        )
                    ),
                    response_mime_type=(
                        "application/json"
                    ),
                    response_schema=(
                        WebProductSearchResponse
                    ),
                    max_output_tokens=1600,
                    temperature=0.1,
                ),
            )
        )

    except Exception as exc:
        elapsed = (
            time.perf_counter()
            - started
        )

        logger.warning(
            "Gemini Google Search failed "
            "(%.1fs): %s",
            elapsed,
            exc,
        )
        return []

    elapsed = (
        time.perf_counter()
        - started
    )

    logger.info(
        "Gemini Google Search completed "
        "(%.1fs): %s",
        elapsed,
        search_query,
    )

    text = str(
        getattr(
            response,
            "text",
            "",
        )
        or ""
    ).strip()

    if not text:
        return []

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "Gemini response was not valid JSON."
        )
        return []

    grounding_urls = (
        extract_grounding_urls(
            response
        )
    )

    return normalize_products(
        payload=payload,
        top_n=top_n,
        grounding_urls=grounding_urls,
        search_query=search_query,
    )


def get_trending_products(
    ingredient_name=None,
    product_type=None,
    top_n=DEFAULT_TOP_N,
    geo=DEFAULT_GEO,
    candidate_n=None,
    **kwargs,
):
    del candidate_n

    if not ingredient_name:
        ingredient_name = (
            kwargs.get("ingredient_en")
            or kwargs.get("ingredient_ko")
            or kwargs.get("ingredient_keyword")
            or ""
        )

    parts = [
        str(
            ingredient_name or ""
        ).strip(),
        str(
            product_type or ""
        ).strip(),
    ]

    search_query = " ".join(
        part
        for part in parts
        if part
    )

    return get_web_product_recommendations(
        search_query=search_query,
        product_type=product_type,
        top_n=top_n,
        geo=geo,
    )


def main():
    query = input(
        "검색할 화장품 조건을 입력하세요: "
    ).strip()

    products = (
        get_web_product_recommendations(
            search_query=query,
            top_n=5,
            geo="KR",
        )
    )

    print(
        json.dumps(
            products,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

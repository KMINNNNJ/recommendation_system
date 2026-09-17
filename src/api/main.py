import logging
import os
import re
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

from src.cosmetics.ingredients.ingredient_repository import (
    recommend_cosmetics,
    recommend_from_user_query,
    resolve_ingredient,
)


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY 환경변수가 없습니다.")

if not OPENAI_MODEL:
    raise ValueError("OPENAI_MODEL 환경변수가 없습니다.")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(
    title="Cosmetics Recommendation API",
    description=(
        "MariaDB, LightFM, Google Trends, Gemini Google Search, "
        "LLM을 활용한 화장품 추천 및 질의응답 API"
    ),
    version="3.0.0",
)


COSMETICS_PERFORMANCE_KEYWORDS = (
    "커버",
    "커버력",
    "블러",
    "블러링",
    "지속력",
    "오래가",
    "오래 가",
    "밀착",
    "밀착력",
    "발색",
    "윤광",
    "글로우",
    "매트",
    "보송",
    "피니시",
)

RECOMMENDATION_CUES = (
    "추천",
    "골라",
    "찾아",
    "찾아줘",
    "좋은 거",
    "좋은거",
    "잘 되는",
    "잘되는",
    "제품",
)

COSMETICS_KEYWORDS = (
    "피부",
    "얼굴",
    "스킨케어",
    "화장품",
    "코스메틱",
    "기초화장",
    "색조",
    "메이크업",
    "피부타입",
    "피부 타입",
    "피부톤",
    "피부 톤",
    "루틴",
    "세럼",
    "앰플",
    "토너",
    "스킨",
    "로션",
    "크림",
    "에센스",
    "클렌저",
    "클렌징",
    "선크림",
    "자외선",
    "마스크팩",
    "시트마스크",
    "파운데이션",
    "쿠션",
    "프라이머",
    "컨실러",
    "파우더",
    "블러셔",
    "하이라이터",
    "브론저",
    "아이섀도",
    "아이라이너",
    "마스카라",
    "립스틱",
    "립틴트",
    "틴트",
    "립밤",
    "보습",
    "수분",
    "유분",
    "피지",
    "모공",
    "블랙헤드",
    "화이트헤드",
    "여드름",
    "트러블",
    "뾰루지",
    "각질",
    "민감성",
    "민감",
    "지성",
    "건성",
    "복합성",
    "중성",
    "홍조",
    "붉음",
    "자극",
    "장벽",
    "탄력",
    "주름",
    "미백",
    "잡티",
    "기미",
    "색소",
    "번들",
    "당겨",
    "건조",
    "촉촉",
    "따갑",
    "가려",
    "진정",
    "나이아신아마이드",
    "레티놀",
    "레티날",
    "히알루론산",
    "하이알루로닉애씨드",
    "살리실산",
    "글리콜산",
    "젖산",
    "비타민c",
    "비타민 c",
    "판테놀",
    "세라마이드",
    "바쿠치올",
    "펩타이드",
    "아데노신",
    "알란토인",
    "병풀",
    "센텔라",
    "스쿠알란",
    "글리세린",
    "아젤라익산",
    "아젤라산",
    "알부틴",
    "트라넥사믹",
    "티트리",
    "aha",
    "bha",
    "pha",
    "skincare",
    "skin care",
    "cosmetic",
    "makeup",
    "serum",
    "toner",
    "moisturizer",
    "cleanser",
    "sunscreen",
    "foundation",
    "cushion",
    "primer",
    "concealer",
    "lipstick",
    "tint",
    "eyeshadow",
    "eyeliner",
    "mascara",
    "acne",
    "pore",
    "oily skin",
    "dry skin",
    "combination skin",
    "sensitive skin",
    "niacinamide",
    "retinol",
    "retinal",
    "hyaluronic acid",
    "salicylic acid",
    "glycolic acid",
    "lactic acid",
    "vitamin c",
    "panthenol",
    "ceramide",
    "bakuchiol",
    "peptide",
    "centella",
    "squalane",
    "glycerin",
    "azelaic acid",
    "arbutin",
    "tranexamic acid",
)

OUT_OF_SCOPE_MESSAGE = (
    "이 서비스는 화장품, 피부 타입, 화장품 성분, "
    "제품 추천 및 성분·제품 트렌드 관련 질문만 지원합니다."
)


class RecommendationRequest(BaseModel):
    ingredient: str = Field(min_length=1, max_length=200)
    product_type: Optional[str] = Field(
        default=None,
        max_length=100,
    )
    skin_type: str = "unknown"
    skin_tone: str = "unknown"
    eye_color: str = "unknown"
    hair_color: str = "unknown"
    top_n: int = Field(default=10, ge=1, le=20)
    trend_top_n: int = Field(default=3, ge=1, le=10)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatIntent(BaseModel):
    intent_type: Literal[
        "general_question",
        "product_recommendation",
        "ingredient_trend",
    ] = "general_question"
    ingredient: str = "unknown"
    top_n: int = Field(default=10, ge=1, le=20)


def _contains_keyword(text, compact_text, keyword):
    keyword = keyword.casefold()
    compact_keyword = re.sub(r"\s+", "", keyword)

    return (
        keyword in text
        or compact_keyword in compact_text
    )


def is_cosmetics_related(message):
    text = str(message).casefold().strip()
    compact_text = re.sub(r"\s+", "", text)

    if not compact_text:
        return False

    if any(
        _contains_keyword(text, compact_text, keyword)
        for keyword in COSMETICS_KEYWORDS
    ):
        return True

    has_performance_keyword = any(
        _contains_keyword(text, compact_text, keyword)
        for keyword in COSMETICS_PERFORMANCE_KEYWORDS
    )
    has_recommendation_cue = any(
        _contains_keyword(text, compact_text, cue)
        for cue in RECOMMENDATION_CUES
    )

    return (
        has_performance_keyword
        and has_recommendation_cue
    )


def normalize_product_type(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value or value.casefold() == "unknown":
        return None

    return value


def parse_chat_intent(message):
    response = client.responses.parse(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "너는 화장품 추천 서비스의 요청 분류기다. "
                    "사용자 질문을 general_question, "
                    "product_recommendation, ingredient_trend 중 하나로 분류한다. "
                    "general_question은 피부 관리, 화장품 성분 설명, 사용 방법, "
                    "메이크업이나 스킨케어에 대한 일반 정보 질문이다. "
                    "product_recommendation은 실제 제품 추천이나 순위를 요청하는 질문이다. "
                    "ingredient_trend는 특정 화장품 성분의 최근 관심도나 "
                    "Google Trends 추세를 묻는 질문이다. "
                    "제품 추천은 성분이나 제품 유형이 빠져 있어도 "
                    "product_recommendation으로 분류한다. "
                    "'지속력 좋은 거 추천', '커버력 좋은 거 추천해줘', "
                    "'밀착 잘 되는 제품 추천' 같은 성능 중심 요청도 포함한다. "
                    "제품 종류는 추측하지 않는다. "
                    "ingredient_trend에서는 사용자가 말한 성분명을 ingredient에 "
                    "가능한 한 그대로 보존한다. "
                    "그 외에는 ingredient를 unknown으로 둬도 된다. "
                    "추천 개수를 따로 말하지 않았다면 top_n은 10이다."
                ),
            },
            {
                "role": "user",
                "content": message,
            },
        ],
        text_format=ChatIntent,
    )

    if response.output_parsed is None:
        raise ValueError("사용자 요청을 분석하지 못했습니다.")

    return response.output_parsed


def generate_general_answer(message):
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "너는 스킨케어와 메이크업을 포함한 화장품 정보를 "
                    "한국어로 설명하는 도우미다. "
                    "사용자의 질문에 직접 답하고, 사용자가 말하지 않은 "
                    "피부 타입이나 상태를 임의로 진단하지 않는다. "
                    "확인되지 않은 제품 효능, 안전성, 성분 농도를 단정하지 않는다. "
                    "질병 진단이나 치료를 대신하지 않는다. "
                    "심한 통증, 부종, 출혈, 지속적인 악화처럼 진료가 필요할 수 있는 "
                    "상황에서는 전문 진료가 필요할 수 있음을 짧게 안내한다. "
                    "화장품과 무관한 주제로 확장하지 않는다. "
                    "답변은 간결하고 자연스럽게 작성한다."
                ),
            },
            {
                "role": "user",
                "content": message,
            },
        ],
    )

    return response.output_text


def get_ingredient_trend(ingredient_name):
    from src.cosmetics.trends.google_trends_collector import (
        collect_keyword_trend,
        summarize_keyword_trend,
    )

    ingredient = resolve_ingredient(ingredient_name)

    if ingredient is None:
        return None, None, "not_found"

    trend_keyword = str(ingredient_name).strip()

    try:
        trend_rows = collect_keyword_trend(
            keyword=trend_keyword,
            geo="KR",
            timeframe="today 12-m",
        )
        trend_summary = summarize_keyword_trend(
            trend_rows
        )

        if trend_summary is None:
            return ingredient, None, "unavailable"

        return ingredient, trend_summary, "available"

    except Exception as error:
        logger.warning(
            "Ingredient trend unavailable: %s",
            type(error).__name__,
        )
        return ingredient, None, "unavailable"


def generate_trend_answer(
    ingredient,
    trend,
    trend_status,
):
    ingredient_name = (
        ingredient.get("ingredient_kr")
        or ingredient.get("ingredient_en")
        or ingredient.get("ingredient_key")
    )

    if trend_status != "available" or trend is None:
        return (
            f"{ingredient_name}의 성분 관심도 데이터는 "
            "현재 조회할 수 없습니다."
        )

    recent = trend.get("recent_average")
    previous = trend.get("previous_average")
    change = trend.get("change_rate")
    latest = trend.get("latest_value")
    peak = trend.get("peak_value")

    try:
        change_value = float(change)
    except (TypeError, ValueError):
        change_value = None

    if change_value is None:
        change_text = "변화율을 계산하기 어렵습니다"
    elif change_value > 0:
        change_text = f"약 {change_value:.1f}% 증가했습니다"
    elif change_value < 0:
        change_text = (
            f"약 {abs(change_value):.1f}% 감소했습니다"
        )
    else:
        change_text = "큰 변화가 없습니다"

    return (
        f'Google Trends에서 "{ingredient_name}" 검색어의 '
        f"최근 4주 평균 관심도 지수는 {recent}, "
        f"직전 4주 평균은 {previous}로 {change_text}. "
        f"최근 값은 {latest}, 최근 12개월 조회 구간의 "
        f"최고 값은 {peak}입니다. "
        "현재 Google Trends 데이터는 최근 12개월을 조회하고, "
        "변화율은 그중 최근 4주와 직전 4주의 평균을 비교합니다. "
        "관심도 지수는 실제 검색 건수가 아니라 선택한 지역과 조회 기간에서의 "
        "상대적 검색 관심도를 0~100으로 정규화한 값입니다."
    )


def generate_recommendation_answer(
    message,
    result,
):
    products = [
        {
            "rank": rank,
            "product_name": product.get("product_name"),
            "brand_name": product.get("brand_name"),
            "rating": product.get("rating"),
            "reviews": product.get("reviews"),
            "price_usd": product.get("price_usd"),
            "product_url": product.get("product_url"),
        }
        for rank, product in enumerate(
            result.get("recommendations", []),
            start=1,
        )
    ]

    ingredient = result.get("ingredient")
    product_type = result.get("product_type")
    user_profile = result.get("user_profile", {})
    trend = result.get("trend")
    trend_keyword = (
        result.get("trend_keyword")
        or result.get("ingredient_query")
        or product_type
    )
    trend_status = result.get(
        "trend_status",
        "available" if trend is not None else "unavailable",
    )
    trend_timeframe = result.get(
        "trend_timeframe",
        "today 12-m",
    )
    trending_products = result.get(
        "trending_products",
        [],
    )
    recommendation_mode = result.get(
        "recommendation_mode",
        "skincare",
    )
    performance_goal = result.get(
        "performance_goal"
    )
    performance_note = result.get(
        "performance_note"
    )
    ranking_method = result.get(
        "ranking_method",
        "lightfm",
    )
    recommendation_note = result.get(
        "recommendation_note"
    )
    web_recommendations = (
        result.get("web_recommendations", [])
        or []
    )
    web_search_query = result.get(
        "web_search_query"
    )
    web_search_status = result.get(
        "web_search_status"
    )

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "화장품 추천 시스템이 계산한 결과를 사용자가 읽기 쉬운 "
                    "한국어로 설명한다. 제공된 추천 순서는 바꾸지 않는다. "
                    "ranking_method가 lightfm이면 LightFM 개인화 모델의 "
                    "순위라고 설명한다. "
                    "catalog_bayesian_fallback이면 LightFM 학습 범위에서 "
                    "추천 가능한 상품이 없어 데이터셋의 평점과 리뷰 수를 함께 "
                    "고려한 대체 순위라고 설명하며, LightFM이 계산한 순위라고 "
                    "말하지 않는다. "
                    "gemini_google_search이면 데이터셋에 조건과 일치하는 상품이 "
                    "없어 Gemini + Google Search로 외부 제품을 탐색한 결과라고 "
                    "설명한다. 이 결과를 LightFM 개인화 순위나 데이터셋 평점 "
                    "순위라고 표현하지 않는다. "
                    "웹 검색 결과에 없는 가격, 평점, 리뷰 수, 판매량은 만들지 않는다. "
                    "웹 제품은 reason과 source_url 범위 안에서만 설명한다. "
                    "내부 점수는 사용자에게 보여주지 않는다. "
                    "성분 필터가 사용된 경우 함유 여부는 데이터베이스에서 이미 "
                    "확인된 것으로 취급한다. "
                    "제품 유형이 지정된 경우 해당 유형으로 후보를 제한했다고 "
                    "설명할 수 있다. "
                    "recommendation_mode가 product_performance이면 성분을 "
                    "자동 선택하지 않은 추천이다. "
                    "현재 데이터에 커버력, 블러, 지속력, 밀착력, 발색 같은 직접 "
                    "성능 측정값이 없으면 실제 성능이 우수하다고 단정하지 않는다. "
                    "피부 타입, 피부톤, 눈 색상, 머리 색상은 추천 모델 입력값일 뿐 "
                    "제품의 의학적 적합성이나 효능을 단정하는 근거로 사용하지 않는다. "
                    "제품명만 보고 효능이나 적합성을 추론하지 않는다. "
                    "상품 설명에는 제공된 제품명, 브랜드, 평점, 리뷰 수, 가격, "
                    "URL만 사용한다. "
                    "Google Trends 값은 실제 검색 건수가 아니라 해당 지역과 "
                    "조회 기간에서의 상대적 관심도를 0~100으로 정규화한 지수다. "
                    "today 12-m 조회에서는 최근 12개월 데이터를 불러오며, "
                    "서비스 변화율은 그중 최근 4주와 직전 4주의 평균을 비교한다. "
                    "조회 기간과 비교 기간을 혼동하지 않는다. "
                    "trend_status가 unavailable이면 상세 오류 대신 검색 관심도 "
                    "데이터를 현재 조회할 수 없다고만 안내한다. "
                    "web_recommendations는 Gemini + Google Search로 확인한 "
                    "외부 제품이며 검색량, 판매량, 개인화 점수를 의미하지 않는다. "
                    "제공되지 않은 정보는 만들지 않고 간결하게 답한다."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"사용자 질문:\n{message}\n\n"
                    f"검색 성분:\n{ingredient}\n\n"
                    f"제품 유형:\n{product_type}\n\n"
                    f"추천 모드:\n{recommendation_mode}\n\n"
                    f"제품 성능 목적:\n{performance_goal}\n\n"
                    f"성능 데이터 안내:\n{performance_note}\n\n"
                    f"추천 순위 방식:\n{ranking_method}\n\n"
                    f"추천 방식 안내:\n{recommendation_note}\n\n"
                    f"웹 검색어:\n{web_search_query}\n\n"
                    f"웹 검색 상태:\n{web_search_status}\n\n"
                    f"웹 검색 제품:\n{web_recommendations}\n\n"
                    f"전체 후보 상품 수:\n"
                    f"{result.get('candidate_count', 0)}\n\n"
                    f"개인화에 사용한 사용자 프로필:\n"
                    f"{user_profile}\n\n"
                    f"추천 결과 순위:\n{products}\n\n"
                    f"Google Trends 검색어:\n{trend_keyword}\n\n"
                    f"Google Trends:\n{trend}\n\n"
                    f"Google Trends 상태:\n{trend_status}\n\n"
                    f"Google Trends 조회 기간:\n"
                    f"{trend_timeframe}\n\n"
                    f"웹 참고 제품:\n{trending_products}"
                ),
            },
        ],
    )

    return response.output_text


def build_missing_info_answer(missing_fields):
    label_map = {
        "ingredient": "원하는 성분",
        "product_type": "제품 종류",
    }
    labels = [
        label_map.get(field, field)
        for field in missing_fields
    ]

    if not labels:
        return "추천에 필요한 정보를 조금 더 알려주세요."

    if len(labels) == 1:
        return f"추천을 위해 {labels[0]}을 알려주세요."

    return (
        "추천을 위해 "
        + ", ".join(labels)
        + "를 알려주세요."
    )


@app.get("/")
def root():
    return {
        "message": "Cosmetics Recommendation API",
        "status": "running",
        "version": "3.0.0",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recommend")
def recommend(request: RecommendationRequest):
    try:
        result = recommend_cosmetics(
            ingredient_name=request.ingredient,
            product_type=normalize_product_type(
                request.product_type
            ),
            skin_type=request.skin_type,
            skin_tone=request.skin_tone,
            eye_color=request.eye_color,
            hair_color=request.hair_color,
            top_n=request.top_n,
            trend_top_n=request.trend_top_n,
        )

        if (
            not result.get("recommendations")
            and not result.get("web_recommendations")
        ):
            product_type_text = (
                f" / {request.product_type}"
                if request.product_type
                else ""
            )

            raise HTTPException(
                status_code=404,
                detail=(
                    f"{request.ingredient}"
                    f"{product_type_text} 조건에서 "
                    "데이터셋과 웹 검색 모두 "
                    "추천 가능한 상품을 찾지 못했습니다."
                ),
            )

        return result

    except HTTPException:
        raise

    except Exception:
        logger.exception("Recommendation request failed")
        raise HTTPException(
            status_code=500,
            detail="추천 처리 중 오류가 발생했습니다.",
        )


@app.post("/chat/recommend")
def chat_recommend(request: ChatRequest):
    message = request.message.strip()

    if not is_cosmetics_related(message):
        return {
            "message": message,
            "type": "out_of_scope",
            "parsed_intent": None,
            "answer": OUT_OF_SCOPE_MESSAGE,
            "result": None,
        }

    try:
        intent = parse_chat_intent(message)

        if intent.intent_type == "general_question":
            return {
                "message": message,
                "type": "general_question",
                "parsed_intent": intent.model_dump(),
                "answer": generate_general_answer(message),
                "result": None,
            }

        if intent.intent_type == "ingredient_trend":
            if (
                not intent.ingredient
                or intent.ingredient == "unknown"
            ):
                return {
                    "message": message,
                    "type": "ingredient_trend",
                    "parsed_intent": intent.model_dump(),
                    "answer": (
                        "어떤 화장품 성분의 트렌드를 "
                        "확인할지 성분명을 알려주세요."
                    ),
                    "result": None,
                }

            ingredient, trend, trend_status = (
                get_ingredient_trend(
                    intent.ingredient
                )
            )

            if ingredient is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "성분을 찾을 수 없습니다: "
                        f"{intent.ingredient}"
                    ),
                )

            return {
                "message": message,
                "type": "ingredient_trend",
                "parsed_intent": intent.model_dump(),
                "answer": generate_trend_answer(
                    ingredient=ingredient,
                    trend=trend,
                    trend_status=trend_status,
                ),
                "result": {
                    "ingredient": ingredient,
                    "trend": trend,
                    "trend_status": trend_status,
                },
            }

        result = recommend_from_user_query(
            user_text=message,
            top_n=intent.top_n,
            trend_top_n=3,
        )

        if result.get("status") == "need_more_info":
            missing_fields = result.get(
                "missing_fields",
                [],
            )

            return {
                "message": message,
                "type": "need_more_info",
                "parsed_intent": intent.model_dump(),
                "parsed_query": result.get(
                    "parsed_query"
                ),
                "answer": build_missing_info_answer(
                    missing_fields
                ),
                "result": result,
            }

        dataset_recommendations = (
            result.get("recommendations")
            or []
        )
        web_recommendations = (
            result.get("web_recommendations")
            or []
        )

        if (
            not dataset_recommendations
            and not web_recommendations
        ):
            parsed_query = result.get(
                "parsed_query",
                {},
            )
            product_type = (
                result.get("product_type")
                or parsed_query.get("product_type")
                or "해당 제품 유형"
            )

            raise HTTPException(
                status_code=404,
                detail=(
                    f"{product_type} 조건에서 "
                    "데이터셋과 웹 검색 모두 "
                    "추천 가능한 상품을 찾지 못했습니다."
                ),
            )

        return {
            "message": message,
            "type": "product_recommendation",
            "parsed_intent": intent.model_dump(),
            "parsed_query": result.get(
                "parsed_query"
            ),
            "answer": generate_recommendation_answer(
                message=message,
                result=result,
            ),
            "result": result,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Chat recommendation request failed")
        raise HTTPException(
            status_code=500,
            detail="질문 처리 중 오류가 발생했습니다.",
        )

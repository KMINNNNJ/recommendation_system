import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite",)


class UserQuery(BaseModel):
    skin_type: Optional[str] = None
    skin_tone: Optional[str] = None
    eye_color: Optional[str] = None
    hair_color: Optional[str] = None

    skin_concerns: list[str] = Field(
        default_factory=list
    )

    ingredient: Optional[str] = None
    product_type: Optional[str] = None

    recommendation_mode: str = "skincare"
    performance_goal: Optional[str] = None

    request_type: str = "recommendation"
    missing_fields: list[str] = Field(
        default_factory=list
    )


SKIN_TYPE_MAP = {
    "건성": "dry",
    "dry": "dry",
    "지성": "oily",
    "oily": "oily",
    "복합성": "combination",
    "combination": "combination",
    "중성": "normal",
    "normal": "normal",
    "민감성": "sensitive",
    "sensitive": "sensitive",
}

SKIN_TONE_MAP = {
    "매우 밝음": "very_light",
    "밝음": "light",
    "보통": "medium",
    "중간": "medium",
    "어두움": "deep",
    "어두운": "deep",
    "매우 어두움": "very_deep",
}

EYE_COLOR_MAP = {
    "갈색": "brown",
    "브라운": "brown",
    "검정": "black",
    "검은색": "black",
    "블랙": "black",
    "헤이즐": "hazel",
    "초록": "green",
    "녹색": "green",
    "파랑": "blue",
    "파란색": "blue",
}

HAIR_COLOR_MAP = {
    "검정": "black",
    "검은색": "black",
    "블랙": "black",
    "갈색": "brown",
    "브라운": "brown",
    "금발": "blonde",
    "블론드": "blonde",
    "빨강": "red",
    "레드": "red",
}

SKIN_CONCERN_ALIASES = {
    "pores": [
        "모공",
        "넓은 모공",
        "모공 고민",
    ],
    "sebum": [
        "피지",
        "유분",
        "번들거림",
        "번들",
        "기름짐",
    ],
    "blackheads": [
        "블랙헤드",
        "화이트헤드",
        "면포",
    ],
    "acne": [
        "여드름",
        "트러블",
        "뾰루지",
    ],
    "dryness": [
        "건조",
        "속건조",
        "당김",
        "수분 부족",
    ],
    "sensitivity": [
        "민감",
        "민감성",
        "자극",
        "따가움",
        "따갑",
    ],
    "redness": [
        "홍조",
        "붉음",
        "붉은기",
    ],
    "barrier": [
        "장벽",
        "피부 장벽",
    ],
    "dullness": [
        "칙칙",
        "칙칙함",
        "생기",
    ],
    "pigmentation": [
        "잡티",
        "기미",
        "색소",
        "색소침착",
    ],
    "wrinkles": [
        "주름",
        "잔주름",
    ],
    "elasticity": [
        "탄력",
        "처짐",
    ],
    "texture": [
        "각질",
        "피부결",
        "거침",
    ],
}

GENERIC_PRODUCT_TYPES = {
    "제품",
    "화장품",
    "화장품 제품",
    "기초",
    "기초 제품",
    "기초제품",
    "기초 화장품",
    "기초화장품",
    "스킨케어",
    "스킨케어 제품",
    "스킨케어제품",
    "스킨 케어",
    "스킨 케어 제품",
    "메이크업",
    "메이크업 제품",
    "메이크업제품",
    "색조",
    "색조 제품",
    "색조제품",
    "색조 화장품",
    "색조화장품",
    "베이스",
    "베이스 제품",
    "베이스제품",
    "베이스 메이크업",
    "클렌징 제품",
    "클렌징제품",
    "skin care",
    "skincare",
    "skincare product",
    "skincare products",
    "cosmetic",
    "cosmetics",
    "cosmetic product",
    "cosmetic products",
    "makeup",
    "makeup product",
    "makeup products",
    "base makeup",
}

PERFORMANCE_STRONG_KEYWORDS = (
    "커버",
    "커버력",
    "블러",
    "블러링",
    "밀착",
    "밀착력",
    "지속력",
    "발색",
)

PERFORMANCE_GOAL_ALIASES = {
    "pore_cover": [
        "모공 커버",
        "모공커버",
        "모공 블러",
        "모공블러",
        "모공 가리",
    ],
    "coverage": [
        "커버력",
        "커버",
        "가려",
    ],
    "blur": [
        "블러링",
        "블러",
    ],
    "longevity": [
        "지속력",
        "오래 가",
        "오래가",
        "무너짐",
    ],
    "adhesion": [
        "밀착력",
        "밀착",
    ],
    "color_payoff": [
        "발색",
    ],
    "dewy_finish": [
        "윤광",
        "글로우",
        "광나는",
    ],
    "matte_finish": [
        "매트",
        "보송",
    ],
}


def normalize_skin_concerns(
    values,
    user_text=None,
):
    if isinstance(values, str):
        values = [values]
    elif not isinstance(values, list):
        values = []

    alias_to_key = {}

    for key, aliases in SKIN_CONCERN_ALIASES.items():
        alias_to_key[key.casefold()] = key

        for alias in aliases:
            alias_to_key[
                str(alias).casefold()
            ] = key

    concerns = []

    for value in values:
        text = str(
            value or ""
        ).strip().casefold()

        if not text:
            continue

        concern = alias_to_key.get(text)

        if (
            concern
            and concern not in concerns
        ):
            concerns.append(concern)

    # 모델이 놓친 피부 고민은 사용자 원문에서 한 번 더 확인한다.
    raw_text = str(
        user_text or ""
    ).casefold()

    for key, aliases in SKIN_CONCERN_ALIASES.items():
        if key in concerns:
            continue

        if any(
            str(alias).casefold() in raw_text
            for alias in aliases
        ):
            concerns.append(key)

    return concerns


def is_generic_product_type(value):
    if value is None:
        return False

    text = str(value).strip().casefold()

    if not text:
        return False

    compact = "".join(
        text.split()
    )

    for generic in GENERIC_PRODUCT_TYPES:
        generic_text = str(
            generic
        ).strip().casefold()

        if (
            text == generic_text
            or compact
            == "".join(generic_text.split())
        ):
            return True

    return False


def detect_recommendation_mode(
    user_text,
    model_value=None,
):
    text = str(
        user_text or ""
    ).strip().casefold()

    if any(
        keyword.casefold() in text
        for keyword in PERFORMANCE_STRONG_KEYWORDS
    ):
        return "product_performance"

    model_text = str(
        model_value or ""
    ).strip().casefold()

    if model_text in {
        "product_performance",
        "performance",
        "makeup_performance",
    }:
        return "product_performance"

    return "skincare"


def normalize_performance_goal(
    user_text,
    model_value=None,
):
    text = str(
        user_text or ""
    ).strip().casefold()

    if (
        "모공" in text
        and any(
            keyword in text
            for keyword in (
                "커버",
                "블러",
                "가리",
            )
        )
    ):
        return "pore_cover"

    for goal, aliases in PERFORMANCE_GOAL_ALIASES.items():
        if any(
            str(alias).casefold() in text
            for alias in aliases
        ):
            return goal

    model_text = str(
        model_value or ""
    ).strip()

    if not model_text:
        return None

    if model_text.casefold() in {
        "none",
        "null",
        "unknown",
    }:
        return None

    return model_text


def normalize_value(
    value,
    mapping,
):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    lowered = text.casefold()

    for key, normalized in mapping.items():
        if key.casefold() == lowered:
            return normalized

    return text


def build_prompt(user_text):
    return f"""
다음 사용자의 화장품 추천 요청을 구조화한다.

사용자 입력:
{user_text}

추출할 정보:
- skin_type:
  dry / oily / combination / normal / sensitive 중 가능한 값

- skin_tone:
  very_light / light / medium / deep / very_deep 중 가능한 값

- eye_color:
  black / brown / hazel / green / blue 등

- hair_color:
  black / brown / blonde / red 등

- skin_concerns:
  사용자가 말한 피부 고민을 리스트로 추출한다.
  가능한 값:
  pores / sebum / blackheads / acne / dryness /
  sensitivity / redness / barrier / dullness /
  pigmentation / wrinkles / elasticity / texture

  예:
  모공 -> pores
  피지, 번들거림 -> sebum
  블랙헤드 -> blackheads
  여드름, 트러블 -> acne
  속건조, 당김 -> dryness
  민감, 자극 -> sensitivity
  홍조, 붉은기 -> redness
  피부 장벽 -> barrier
  칙칙함 -> dullness
  잡티, 기미, 색소침착 -> pigmentation
  주름 -> wrinkles
  탄력 -> elasticity
  각질, 피부결 -> texture

- ingredient:
  사용자가 언급한 화장품 성분명.
  가능한 한 사용자가 입력한 한국어 표현을 유지한다.

- product_type:
  사용자가 원하는 구체적인 제품 유형.
  예:
  세럼, 앰플, 토너, 크림, 로션, 파운데이션,
  쿠션, 프라이머, 립스틱, 틴트, 아이섀도,
  아이라이너, 마스카라 등

- recommendation_mode:
  skincare / product_performance 중 하나.

  skincare:
  피부 상태나 피부 고민 자체를 관리하거나 개선하기 위한
  스킨케어 제품 요청.

  예:
  "모공이 고민인데 세럼 추천해줘"
  "건조한 피부에 쓸 크림 추천해줘"

  product_performance:
  화장품 사용 시 표현력이나 제품 성능을 원하는 요청.

  예:
  "모공 커버 잘 되는 프라이머 추천해줘"
  "커버력 좋은 파운데이션"
  "지속력 좋은 쿠션"
  "발색 좋은 립스틱"

  "모공", "잡티", "홍조" 같은 피부 관련 단어가 있더라도
  사용자가 커버, 가리기, 블러, 지속력, 밀착력, 발색 같은
  표현 성능을 원하면 product_performance다.

- performance_goal:
  product_performance일 때만 가능한 한 아래 값 중 하나로 추출한다.
  pore_cover / coverage / blur / longevity /
  adhesion / color_payoff / dewy_finish / matte_finish
  해당하지 않으면 null.

- request_type:
  기본값은 recommendation.

규칙:
1. 사용자가 말하지 않은 정보는 추측하지 말고 null로 둔다.
2. 피부톤과 피부타입을 혼동하지 않는다.
3. 제품 유형이 명시되지 않았다면 null로 둔다.
4. "기초 제품", "스킨케어 제품", "화장품", "제품",
   "메이크업 제품", "색조 제품", "베이스 제품"처럼
   범위가 넓은 표현은 구체적인 product_type으로 인정하지 않는다.
5. 세럼, 앰플, 토너, 크림, 로션, 에센스, 클렌저,
   선크림, 파운데이션, 쿠션, 프라이머, 컨실러,
   파우더, 블러셔, 립스틱, 틴트, 아이섀도,
   아이라이너, 마스카라처럼 실제 제품 형태가 특정될 때만
   product_type을 채운다.
6. 성분이 명시되지 않았다면 ingredient는 null로 둔다.
7. recommendation_mode가 skincare이고 사용자가 성분을 말하지 않았더라도
   skin_type 또는 skin_concerns가 있으면 다음 단계에서
   성분을 자동 선택할 수 있다.
8. recommendation_mode가 product_performance이면 성분은 필수 정보가 아니다.
9. product_performance에서 사용자가 성분을 직접 지정한 경우에는
   ingredient를 그대로 유지한다.
10. skincare이면서 skin_type도 없고 skin_concerns도 없고
    ingredient도 없다면 ingredient를 missing_fields에 넣는다.
11. 눈 색상이나 머리 색상은 사용자가 말한 경우만 추출한다.
12. 제품 유형이 없거나 너무 넓으면 product_type을
    missing_fields에 넣는다.
13. 예:
    "모공이 고민인데 세럼 추천" -> skincare
    "모공 커버 잘 되는 프라이머" -> product_performance
    "모공 커버 잘 되는 제품" -> product_performance,
    product_type=null, ingredient는 missing_fields에 넣지 않음
14. JSON 구조 외 설명은 하지 않는다.
""".strip()


def parse_user_query(user_text):
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY가 .env에 없습니다."
        )

    user_text = str(
        user_text or ""
    ).strip()

    if not user_text:
        raise ValueError(
            "사용자 입력이 비어 있습니다."
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    chat = client.chats.create(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=UserQuery,
            temperature=0.0,
            max_output_tokens=500,
        ),
    )

    response = chat.send_message(
        build_prompt(user_text)
    )

    response_text = str(
        getattr(response, "text", "")
        or ""
    ).strip()

    if not response_text:
        raise RuntimeError(
            "Gemini 응답이 비어 있습니다."
        )

    data = json.loads(response_text)

    data["skin_type"] = normalize_value(
        data.get("skin_type"),
        SKIN_TYPE_MAP,
    )
    data["skin_tone"] = normalize_value(
        data.get("skin_tone"),
        SKIN_TONE_MAP,
    )
    data["eye_color"] = normalize_value(
        data.get("eye_color"),
        EYE_COLOR_MAP,
    )
    data["hair_color"] = normalize_value(
        data.get("hair_color"),
        HAIR_COLOR_MAP,
    )

    data["skin_concerns"] = (
        normalize_skin_concerns(
            data.get("skin_concerns"),
            user_text=user_text,
        )
    )

    ingredient = data.get("ingredient")
    product_type = data.get("product_type")

    if ingredient is not None:
        ingredient = (
            str(ingredient).strip()
            or None
        )

    if product_type is not None:
        product_type = (
            str(product_type).strip()
            or None
        )

    # 모델이 넓은 표현을 제품 유형으로 반환해도 서버에서 다시 거른다.
    if is_generic_product_type(
        product_type
    ):
        product_type = None

    recommendation_mode = (
        detect_recommendation_mode(
            user_text=user_text,
            model_value=data.get(
                "recommendation_mode"
            ),
        )
    )

    performance_goal = (
        normalize_performance_goal(
            user_text=user_text,
            model_value=data.get(
                "performance_goal"
            ),
        )
    )

    if (
        recommendation_mode
        != "product_performance"
    ):
        performance_goal = None

    data["ingredient"] = ingredient
    data["product_type"] = product_type
    data["recommendation_mode"] = (
        recommendation_mode
    )
    data["performance_goal"] = (
        performance_goal
    )

    missing_fields = []

    can_auto_select_ingredient = (
        recommendation_mode == "skincare"
        and bool(
            data.get("skin_type")
            or data.get("skin_concerns")
        )
    )

    if (
        recommendation_mode == "skincare"
        and not ingredient
        and not can_auto_select_ingredient
    ):
        missing_fields.append(
            "ingredient"
        )

    if not product_type:
        missing_fields.append(
            "product_type"
        )

    data["missing_fields"] = (
        missing_fields
    )

    return data


def main():
    user_text = input(
        "사용자 질문을 입력하세요: "
    ).strip()

    result = parse_user_query(
        user_text
    )

    print()
    print("[질의 분석 결과]")
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

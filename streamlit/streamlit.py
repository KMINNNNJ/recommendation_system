import html
import textwrap

import requests
import streamlit as st


API_URL = "http://127.0.0.1:8000/chat/recommend"

SKIN_TYPE_LABELS = {
    "oily": "지성",
    "dry": "건성",
    "combination": "복합성",
    "normal": "중성",
    "sensitive": "민감성",
    "unknown": "-",
}

CONCERN_LABELS = {
    "pores": "모공",
    "sebum": "피지·유분",
    "blackheads": "블랙헤드",
    "acne": "트러블",
    "dryness": "건조·속건조",
    "sensitivity": "민감·자극",
    "redness": "홍조·붉은기",
    "barrier": "피부 장벽",
    "dullness": "칙칙함",
    "pigmentation": "잡티·색소",
    "wrinkles": "주름",
    "elasticity": "탄력",
    "texture": "각질·피부결",
}

PERFORMANCE_GOAL_LABELS = {
    "pore_cover": "모공 커버·블러",
    "coverage": "커버력",
    "blur": "블러 표현",
    "longevity": "지속력",
    "adhesion": "밀착력",
    "color_payoff": "발색",
    "dewy_finish": "윤광 표현",
    "matte_finish": "매트·보송 표현",
}

TREND_TIMEFRAME_LABELS = {
    "today 12-m": "최근 12개월",
    "today 3-m": "최근 3개월",
    "today 1-m": "최근 1개월",
    "today 5-y": "최근 5년",
}


st.set_page_config(
    page_title="BeautyLens",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_CSS = '\n    <style>\n\n    /* 전체 화면 */\n    .stApp {\n        background:\n            linear-gradient(\n                180deg,\n                #fffafb 0%,\n                #ffffff 45%,\n                #fff8f7 100%\n            );\n    }\n\n    .block-container {\n        max-width: 1100px;\n        padding-top: 2.2rem;\n        padding-bottom: 5rem;\n    }\n\n    /* Streamlit 기본 요소 숨김 */\n    #MainMenu {\n        visibility: hidden;\n    }\n\n    footer {\n        visibility: hidden;\n    }\n\n    header {\n        visibility: hidden;\n    }\n\n    /* 상단 로고 */\n    .brand {\n        font-size: 14px;\n        font-weight: 700;\n        letter-spacing: 1.8px;\n        color: #d36c82;\n        margin-bottom: 12px;\n    }\n\n    /* 메인 타이틀 */\n    .hero-title {\n        font-size: 48px;\n        line-height: 1.12;\n        font-weight: 800;\n        letter-spacing: -1.8px;\n        color: #222222;\n        margin-bottom: 14px;\n    }\n\n    .hero-title span {\n        color: #d86f87;\n    }\n\n    .hero-subtitle {\n        color: #777777;\n        font-size: 17px;\n        line-height: 1.7;\n        margin-bottom: 34px;\n    }\n\n    /* 상태 표시 */\n    .status-row {\n        display: flex;\n        gap: 10px;\n        flex-wrap: wrap;\n        margin-bottom: 34px;\n    }\n\n    .status-chip {\n        display: inline-block;\n        padding: 8px 13px;\n        border-radius: 100px;\n        background: #ffffff;\n        border: 1px solid #f0dfe3;\n        font-size: 13px;\n        color: #666666;\n    }\n\n    /* 사용자 질문 */\n    .user-question {\n        margin-left: auto;\n        max-width: 75%;\n        width: fit-content;\n        background: #262626;\n        color: white;\n        padding: 15px 19px;\n        border-radius: 20px 20px 5px 20px;\n        font-size: 15px;\n        line-height: 1.6;\n        margin-top: 20px;\n        margin-bottom: 22px;\n    }\n\n    /* AI 영역 */\n    .ai-label {\n        font-size: 13px;\n        font-weight: 700;\n        color: #d36c82;\n        margin-bottom: 10px;\n    }\n\n    .answer-box {\n        background: white;\n        border: 1px solid #f0e5e7;\n        border-radius: 22px;\n        padding: 24px 26px;\n        box-shadow: 0 8px 30px rgba(35, 20, 25, 0.05);\n        margin-bottom: 26px;\n    }\n\n    /* AI 답변 컨테이너 */\n    div[data-testid="stVerticalBlockBorderWrapper"] {\n        background: #ffffff;\n        border: 1px solid #f0e5e7 !important;\n        border-radius: 22px !important;\n        box-shadow: 0 8px 30px rgba(35, 20, 25, 0.05);\n        margin-bottom: 26px;\n    }\n\n    div[data-testid="stVerticalBlockBorderWrapper"]\n    > div[data-testid="stVerticalBlock"] {\n        padding: 6px 8px;\n    }\n\n    /* 추천 기준 */\n    .basis-card {\n        background: linear-gradient(\n            135deg,\n            #fff8fa,\n            #fffdfd\n        );\n        border: 1px solid #f1dfe4;\n        border-radius: 20px;\n        padding: 20px 22px;\n        margin: 18px 0 22px 0;\n        box-shadow: 0 6px 22px rgba(35, 20, 25, 0.035);\n    }\n\n    .basis-title {\n        font-size: 12px;\n        font-weight: 800;\n        letter-spacing: 1px;\n        color: #b16b7d;\n        margin-bottom: 12px;\n    }\n\n    .basis-grid {\n        display: grid;\n        grid-template-columns: repeat(2, minmax(0, 1fr));\n        gap: 10px 18px;\n    }\n\n    .basis-item {\n        background: #ffffff;\n        border: 1px solid #f4e9ec;\n        border-radius: 14px;\n        padding: 12px 14px;\n    }\n\n    .basis-label {\n        font-size: 11px;\n        font-weight: 700;\n        color: #a28b91;\n        margin-bottom: 5px;\n    }\n\n    .basis-value {\n        font-size: 14px;\n        font-weight: 700;\n        color: #332a2d;\n        line-height: 1.45;\n        word-break: keep-all;\n    }\n\n    .basis-note {\n        margin-top: 12px;\n        color: #8a777d;\n        font-size: 12px;\n        line-height: 1.55;\n    }\n\n    @media (max-width: 700px) {\n        .basis-grid {\n            grid-template-columns: 1fr;\n        }\n    }\n\n    /* 성분 정보 */\n    .ingredient-card {\n        background: linear-gradient(\n            135deg,\n            #fff1f4,\n            #fff9f8\n        );\n        border: 1px solid #f3dce2;\n        border-radius: 18px;\n        padding: 20px 22px;\n        margin: 18px 0 25px 0;\n    }\n\n    .ingredient-label {\n        color: #9b7880;\n        font-size: 12px;\n        font-weight: 700;\n        letter-spacing: 1px;\n        margin-bottom: 5px;\n    }\n\n    .ingredient-name {\n        font-size: 23px;\n        font-weight: 800;\n        color: #252525;\n    }\n\n    .candidate-text {\n        color: #85777a;\n        font-size: 13px;\n        margin-top: 5px;\n    }\n\n    /* 제품 카드 */\n    .product-card {\n        background: white;\n        border: 1px solid #ede7e8;\n        border-radius: 20px;\n        padding: 22px;\n        height: 100%;\n        box-shadow: 0 6px 20px rgba(25, 15, 18, 0.04);\n        transition: 0.2s ease;\n        margin-bottom: 8px;\n    }\n\n    .product-card:hover {\n        border-color: #e7bbc5;\n        transform: translateY(-2px);\n        box-shadow: 0 10px 28px rgba(30, 15, 20, 0.07);\n    }\n\n    .rank {\n        display: inline-flex;\n        align-items: center;\n        justify-content: center;\n        width: 32px;\n        height: 32px;\n        background: #fce8ed;\n        color: #c35e76;\n        border-radius: 10px;\n        font-weight: 800;\n        font-size: 14px;\n        margin-bottom: 16px;\n    }\n\n    .product-brand {\n        color: #c27082;\n        font-size: 12px;\n        font-weight: 700;\n        margin-bottom: 6px;\n    }\n\n    .product-name {\n        font-size: 17px;\n        font-weight: 750;\n        color: #262626;\n        line-height: 1.4;\n        min-height: 48px;\n        margin-bottom: 18px;\n    }\n\n    .product-name a {\n        color: #262626;\n        text-decoration: none;\n    }\n\n    .product-name a:hover {\n        color: #d86f87;\n        text-decoration: underline;\n    }\n\n    .product-info {\n        border-top: 1px solid #f1eeee;\n        padding-top: 14px;\n        color: #777777;\n        font-size: 13px;\n        line-height: 1.8;\n    }\n\n    .product-link {\n        display: inline-block;\n        margin-top: 14px;\n        padding: 9px 13px;\n        border-radius: 10px;\n        background: #fff1f4;\n        border: 1px solid #f2d9df;\n        color: #c85f78;\n        font-size: 13px;\n        font-weight: 800;\n        text-decoration: none;\n        transition: 0.2s ease;\n    }\n\n    .product-link:hover {\n        background: #fce6eb;\n        border-color: #e9bdc7;\n        color: #aa4961;\n        text-decoration: none;\n        transform: translateY(-1px);\n    }\n\n    .price {\n        font-size: 16px;\n        color: #333333;\n        font-weight: 800;\n    }\n\n    .price-note {\n        display: inline-block;\n        margin-top: 2px;\n        color: #999999;\n        font-size: 11px;\n        font-weight: 500;\n    }\n\n    /* Trends */\n    .web-mention-note {\n        margin-top: 10px;\n        margin-bottom: 14px;\n        color: #7a6a6f;\n        font-size: 0.90rem;\n        line-height: 1.55;\n    }\n\n    .web-mention-card {\n        background: #ffffff;\n        border: 1px solid #f0e5e7;\n        border-radius: 18px;\n        padding: 18px 20px;\n        margin-bottom: 12px;\n        box-shadow: 0 6px 22px rgba(35, 20, 25, 0.04);\n    }\n\n    .web-mention-rank {\n        font-size: 0.72rem;\n        letter-spacing: 0.12em;\n        color: #a98b92;\n        font-weight: 700;\n        margin-bottom: 5px;\n    }\n\n    .web-mention-name {\n        font-size: 1.02rem;\n        font-weight: 700;\n        color: #2f2528;\n        margin-bottom: 7px;\n    }\n\n    .web-mention-meta {\n        font-size: 0.88rem;\n        color: #786b6f;\n        line-height: 1.5;\n    }\n\n    .trend-card {\n        margin-top: 30px;\n        padding: 23px 25px;\n        border-radius: 20px;\n        background: #282828;\n        color: white;\n    }\n\n    .trend-title {\n        font-size: 13px;\n        color: #d8d8d8;\n        margin-bottom: 10px;\n        font-weight: 600;\n    }\n\n    .trend-number {\n        font-size: 30px;\n        font-weight: 800;\n        margin-bottom: 5px;\n    }\n\n    .trend-desc {\n        color: #cccccc;\n        font-size: 13px;\n        line-height: 1.6;\n    }\n\n    /* 섹션 제목 */\n    .section-title {\n        font-size: 23px;\n        font-weight: 800;\n        color: #262626;\n        margin-top: 15px;\n        margin-bottom: 5px;\n    }\n\n    .section-caption {\n        color: #888888;\n        font-size: 13px;\n        margin-bottom: 20px;\n    }\n\n    /* 채팅 입력 */\n    [data-testid="stChatInput"] {\n        background: white;\n        border-radius: 20px;\n    }\n\n    [data-testid="stChatInput"] textarea {\n        font-size: 15px;\n    }\n\n    </style>\n    '
st.markdown(
    APP_CSS,
    unsafe_allow_html=True,
)


def safe(value):
    if value is None:
        return "-"

    return html.escape(
        str(value)
    )


def show_product_card(
    product,
    rank,
):
    product_name = safe(
        product.get("product_name")
    )
    brand_name = safe(
        product.get("brand_name")
    )

    rating = product.get("rating")
    reviews = product.get("reviews")
    price = product.get("price_usd")
    latest_review_date = product.get(
        "latest_review_date"
    )
    product_url = product.get(
        "product_url"
    )

    if product_url:
        escaped_url = safe(
            product_url
        )
        product_name_html = (
            f'<a href="{escaped_url}" '
            f'target="_blank" '
            f'rel="noopener noreferrer">'
            f'{product_name}</a>'
        )
        product_link_html = (
            f'<a class="product-link" '
            f'href="{escaped_url}" '
            f'target="_blank" '
            f'rel="noopener noreferrer">'
            f'제품 보기 →</a>'
        )
    else:
        product_name_html = product_name
        product_link_html = ""

    rating_text = (
        f"{float(rating):.2f}"
        if rating is not None
        else "-"
    )
    reviews_text = (
        f"{int(reviews):,}"
        if reviews is not None
        else "-"
    )

    if price is not None:
        price_text = (
            f"${float(price):g}"
        )

        if latest_review_date:
            price_note = (
                "데이터셋 가격 · 해당 상품 최신 리뷰일 "
                f"{safe(latest_review_date)}"
            )
        else:
            price_note = "데이터셋 가격"
    else:
        price_text = "가격 정보 없음"
        price_note = ""

    card_html = (
        f'<div class="product-card">'
        f'<div class="rank">{rank}</div>'
        f'<div class="product-brand">{brand_name}</div>'
        f'<div class="product-name">{product_name_html}</div>'
        f'<div class="product-info">'
        f'평점 {rating_text}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'리뷰 {reviews_text}개'
        f'<br>'
        f'<span class="price">{price_text}</span>'
        f'<br>'
        f'<span class="price-note">{price_note}</span>'
        f'</div>'
        f'{product_link_html}'
        f'</div>'
    )

    st.markdown(
        card_html,
        unsafe_allow_html=True,
    )


def get_ingredient_query(result):
    ingredient = (
        result.get("ingredient")
        or {}
    )
    selection = (
        result.get("ingredient_selection")
        or {}
    )

    return (
        result.get("ingredient_query")
        or selection.get("ingredient_name")
        or ingredient.get("ingredient_kr")
        or ingredient.get("ingredient_en")
        or "-"
    )


def build_basis_content(result):
    user_profile = (
        result.get("user_profile")
        or {}
    )
    ingredient_selection = (
        result.get("ingredient_selection")
        or {}
    )

    ingredient_source = result.get(
        "ingredient_source"
    )
    recommendation_mode = result.get(
        "recommendation_mode",
        "skincare",
    )
    ranking_method = result.get(
        "ranking_method",
        "lightfm",
    )
    performance_goal = result.get(
        "performance_goal"
    )

    ingredient_query = (
        get_ingredient_query(
            result
        )
    )
    product_type = (
        result.get("product_type")
        or user_profile.get("product_type")
        or "-"
    )

    skin_type = (
        user_profile.get("skin_type")
        or "-"
    )
    skin_type_text = (
        SKIN_TYPE_LABELS.get(
            skin_type,
            skin_type,
        )
    )

    concerns = (
        user_profile.get("skin_concerns")
        or []
    )
    concern_texts = [
        CONCERN_LABELS.get(
            concern,
            concern,
        )
        for concern in concerns
    ]
    concerns_text = (
        ", ".join(concern_texts)
        if concern_texts
        else "-"
    )

    if (
        recommendation_mode
        == "product_performance"
    ):
        ingredient_basis_label = (
            "요청 목적"
        )
        ingredient_basis_text = (
            PERFORMANCE_GOAL_LABELS.get(
                performance_goal,
                "제품 사용 성능",
            )
        )

        if (
            ranking_method
            == "gemini_google_search"
        ):
            note = (
                "성분 자동 선택 없이 제품 유형과 요청 목적을 사용했습니다. "
                "데이터셋에 일치하는 상품이 없어 Gemini + Google Search로 "
                "외부 제품을 실시간 탐색했습니다. "
                "커버력·블러·지속력 같은 직접 성능 측정 순위는 아닙니다."
            )
        elif (
            ranking_method
            == "catalog_bayesian_fallback"
        ):
            note = (
                "성분 자동 선택 없이 제품 유형으로 후보를 좁혔습니다. "
                "LightFM 학습 범위에서 추천 결과가 없어 "
                "데이터셋 평점과 리뷰 수를 함께 고려한 "
                "대체 순위를 제공합니다."
            )
        else:
            note = (
                "성분 자동 선택 없이 제품 유형으로 후보를 좁힌 뒤 "
                "LightFM이 개인화 순위를 계산합니다. "
                "현재 데이터에는 커버력·블러·지속력 같은 "
                "직접 성능 측정값이 없어 해당 성능이 "
                "실제로 우수하다고 단정하는 순위는 아닙니다."
            )

    else:
        ingredient_basis_label = (
            "탐색 성분"
        )

        if ingredient_source == "user":
            ingredient_basis_text = (
                f"{ingredient_query} "
                "(사용자 지정)"
            )
        elif ingredient_selection:
            basis_label = (
                ingredient_selection.get(
                    "basis_label"
                )
                or "피부 정보"
            )
            ingredient_basis_text = (
                f"{ingredient_query} "
                f"({basis_label} 기준 자동 선택)"
            )
        else:
            ingredient_basis_text = str(
                ingredient_query
            )

        note = (
            "피부 정보와 성분으로 후보 상품을 좁힌 뒤 "
            "LightFM이 개인화 순위를 계산합니다. "
            "Google Trends와 최근 웹 언급은 아래에서 "
            "별도 참고 정보로 제공합니다."
        )

    if (
        ranking_method
        == "catalog_bayesian_fallback"
    ):
        model_text = (
            "평점·리뷰 기반 대체 순위"
        )
    elif (
        ranking_method
        == "gemini_google_search"
    ):
        model_text = (
            "Gemini + Google Search"
        )
    else:
        model_text = (
            "LightFM 개인화 모델"
        )

    return {
        "skin_type": skin_type_text,
        "concerns": concerns_text,
        "ingredient_label": (
            ingredient_basis_label
        ),
        "ingredient": ingredient_basis_text,
        "product_type": product_type,
        "candidate_count": (
            result.get("candidate_count")
            or 0
        ),
        "model": model_text,
        "note": note,
    }


def show_basis_card(result):
    basis = build_basis_content(
        result
    )

    basis_html = (
        f'<div class="basis-card">'
        f'<div class="basis-title">RECOMMENDATION BASIS</div>'
        f'<div class="basis-grid">'
        f'<div class="basis-item">'
        f'<div class="basis-label">피부 타입</div>'
        f'<div class="basis-value">{safe(basis["skin_type"])}</div>'
        f'</div>'
        f'<div class="basis-item">'
        f'<div class="basis-label">피부 고민</div>'
        f'<div class="basis-value">{safe(basis["concerns"])}</div>'
        f'</div>'
        f'<div class="basis-item">'
        f'<div class="basis-label">{safe(basis["ingredient_label"])}</div>'
        f'<div class="basis-value">{safe(basis["ingredient"])}</div>'
        f'</div>'
        f'<div class="basis-item">'
        f'<div class="basis-label">제품 유형</div>'
        f'<div class="basis-value">{safe(basis["product_type"])}</div>'
        f'</div>'
        f'<div class="basis-item">'
        f'<div class="basis-label">후보 상품</div>'
        f'<div class="basis-value">{basis["candidate_count"]:,}개</div>'
        f'</div>'
        f'<div class="basis-item">'
        f'<div class="basis-label">개인화 모델</div>'
        f'<div class="basis-value">{safe(basis["model"])}</div>'
        f'</div>'
        f'</div>'
        f'<div class="basis-note">{safe(basis["note"])}</div>'
        f'</div>'
    )

    st.markdown(
        basis_html,
        unsafe_allow_html=True,
    )


def show_recommendations(result):
    recommendations = (
        result.get("recommendations")
        or []
    )

    if not recommendations:
        return

    ranking_method = result.get(
        "ranking_method",
        "lightfm",
    )
    recommendation_note = result.get(
        "recommendation_note"
    )

    if (
        ranking_method
        == "catalog_bayesian_fallback"
    ):
        title = "Dataset Picks"
        caption = (
            recommendation_note
            or (
                "LightFM 학습 범위에서 추천 가능한 상품이 없어 "
                "평점과 리뷰 수를 함께 고려한 대체 순위를 제공합니다."
            )
        )
    else:
        title = "Personalized Picks"
        caption = (
            "LightFM 개인화 모델이 후보 상품의 순위를 계산했습니다."
        )

    st.markdown(
        '<div class="section-title">'
        f'{safe(title)}'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-caption">'
        f'{safe(caption)}'
        '</div>',
        unsafe_allow_html=True,
    )

    for start in range(
        0,
        len(recommendations),
        2,
    ):
        columns = st.columns(2)
        chunk = recommendations[
            start:start + 2
        ]

        for index, product in enumerate(
            chunk
        ):
            if not isinstance(
                product,
                dict,
            ):
                continue

            with columns[index]:
                show_product_card(
                    product=product,
                    rank=start + index + 1,
                )


def show_web_products(
    products,
    *,
    title,
    caption=None,
    rank_label="WEB SEARCH",
):
    if not products:
        return

    st.markdown(
        '<div class="section-title">'
        f'{safe(title)}'
        '</div>',
        unsafe_allow_html=True,
    )

    if caption:
        st.markdown(
            '<div class="section-caption">'
            f'{caption}'
            '</div>',
            unsafe_allow_html=True,
        )

    for index, product in enumerate(
        products,
        start=1,
    ):
        if not isinstance(
            product,
            dict,
        ):
            continue

        brand_name = safe(
            product.get("brand_name")
            or ""
        )
        product_name = safe(
            product.get("product_name")
            or "제품명 미확인"
        )
        reason = safe(
            product.get("reason")
            or "검색 결과에서 관련 제품으로 확인되었습니다."
        )

        source_url = str(
            product.get("source_url")
            or ""
        ).strip()

        if source_url:
            source_html = (
                f'<a href="{safe(source_url)}" '
                f'target="_blank" '
                f'rel="noopener noreferrer">'
                f'근거 출처 보기 ↗</a>'
            )
        else:
            source_html = (
                "근거 URL 미확인"
            )

        display_name = (
            f"{brand_name} {product_name}"
            .strip()
        )

        web_html = textwrap.dedent(
            f"""
            <div class="web-mention-card">
                <div class="web-mention-rank">
                    {rank_label} {index}
                </div>
                <div class="web-mention-name">
                    {display_name}
                </div>
                <div class="web-mention-meta">
                    {reason}
                    <br><br>
                    {source_html}
                </div>
            </div>
            """
        ).strip()

        st.markdown(
            web_html,
            unsafe_allow_html=True,
        )


def show_trend(result):
    trend = (
        result.get("trend")
        or {}
    )

    if not trend:
        return

    trend_keyword = (
        result.get("trend_keyword")
        or result.get("ingredient_query")
        or result.get("product_type")
        or "-"
    )
    trend_timeframe = (
        result.get("trend_timeframe")
        or "today 12-m"
    )
    timeframe_label = (
        TREND_TIMEFRAME_LABELS.get(
            trend_timeframe,
            trend_timeframe,
        )
    )

    change_rate = trend.get(
        "change_rate"
    )
    recent_average = trend.get(
        "recent_average"
    )
    previous_average = trend.get(
        "previous_average"
    )

    try:
        recent_number = float(
            recent_average or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        recent_number = 0.0

    try:
        previous_number = float(
            previous_average or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        previous_number = 0.0

    keyword_text = (
        f'"{safe(trend_keyword)}"'
    )

    if (
        change_rate is None
        and recent_number > 0
        and previous_number == 0
    ):
        change_text = "증감률 계산 불가"
        trend_sentence = (
            f"최근 4주 동안 {keyword_text}의 "
            f"Google 검색 관심도 지수 평균은 "
            f"{safe(recent_average)}입니다. "
            "직전 4주 평균이 0이어서 "
            "퍼센트 증감률은 계산하지 않았습니다."
        )
    elif change_rate is None:
        change_text = "비교 데이터 없음"
        trend_sentence = (
            f"{keyword_text}는 최근 8주 비교 구간에서 "
            "충분한 Google Trends 관심도 신호를 "
            "확인하지 못했습니다."
        )
    elif change_rate > 0:
        change_text = (
            f"+{change_rate:.1f}%"
        )
        trend_sentence = (
            f"최근 4주 동안 {keyword_text}의 "
            f"Google 검색 관심도 지수 평균이 "
            f"직전 4주보다 {abs(change_rate):.1f}% "
            "상승했습니다."
        )
    elif change_rate < 0:
        change_text = (
            f"{change_rate:.1f}%"
        )
        trend_sentence = (
            f"최근 4주 동안 {keyword_text}의 "
            f"Google 검색 관심도 지수 평균이 "
            f"직전 4주보다 {abs(change_rate):.1f}% "
            "감소했습니다."
        )
    else:
        change_text = "0%"
        trend_sentence = (
            f"최근 4주 동안 {keyword_text}의 "
            "Google 검색 관심도 지수 평균은 "
            "직전 4주와 같습니다."
        )

    trend_html = textwrap.dedent(
        f"""
        <div class="trend-card">
            <div class="trend-title">
                GOOGLE TRENDS · KOREA
            </div>
            <div class="trend-desc">
                검색어 · <strong>{safe(trend_keyword)}</strong>
            </div>
            <div class="trend-number">
                {change_text}
            </div>
            <div class="trend-desc">
                {trend_sentence}
                <br>
                최근 4주 평균 지수
                <strong>{safe(recent_average)}</strong>
                · 직전 4주 평균 지수
                <strong>{safe(previous_average)}</strong>
                <br><br>
                Google Trends에서는
                <strong>{safe(timeframe_label)}</strong>
                데이터를 조회합니다.
                이 카드의 증감률은 그 전체 조회 데이터 중
                <strong>최근 4주 평균과 직전 4주 평균</strong>을
                비교한 값입니다.
                <br><br>
                관심도 지수는 실제 검색 건수가 아니라,
                선택한 지역과 조회 기간에서 해당 검색어의
                상대적 검색 관심도를 0~100으로 정규화한 값입니다.
                100은 해당 조회 기간에서 검색 관심도가
                가장 높았던 시점을 뜻합니다.
                따라서 지수 63.75는 검색 63.75건을 의미하지 않습니다.
            </div>
        </div>
        """
    ).strip()

    st.markdown(
        trend_html,
        unsafe_allow_html=True,
    )


def show_result(data):
    if not isinstance(
        data,
        dict,
    ):
        st.error(
            "응답 형식이 올바르지 않습니다."
        )
        return

    response_type = data.get(
        "type",
        "",
    )
    result = (
        data.get("result")
        or {}
    )
    answer = (
        data.get("answer")
        or ""
    )

    st.markdown(
        '<div class="ai-label">'
        'AI BEAUTY ASSISTANT'
        '</div>',
        unsafe_allow_html=True,
    )

    if answer:
        with st.container(
            border=True
        ):
            st.markdown(
                answer
            )

    if response_type == "need_more_info":
        return

    if response_type == "product_recommendation":
        show_basis_card(
            result
        )

    show_recommendations(
        result
    )

    web_recommendations = (
        result.get("web_recommendations")
        or []
    )

    if (
        response_type
        == "product_recommendation"
        and not result.get("recommendations")
        and not web_recommendations
    ):
        st.caption(
            "현재 조건에서는 데이터셋과 웹 검색 모두 "
            "추천 가능한 상품을 찾지 못했습니다."
        )

    if web_recommendations:
        web_search_query = (
            result.get("web_search_query")
            or "-"
        )
        caption = (
            "데이터셋에 현재 조건과 일치하는 상품이 없어 "
            "Gemini + Google Search로 "
            f"<strong>{safe(web_search_query)}</strong> 관련 제품을 "
            "실시간 탐색했습니다. "
            "아래 결과는 LightFM 개인화 순위가 아닙니다."
        )

        show_web_products(
            web_recommendations,
            title="Web Search Picks",
            caption=caption,
            rank_label="WEB SEARCH",
        )

    trending_products = (
        result.get("trending_products")
        or []
    )

    if trending_products:
        caption = (
            "Gemini + Google Search에서 확인한 보조 웹 결과입니다. "
            "검색량이나 LightFM 개인화 순위를 의미하지 않습니다."
        )

        show_web_products(
            trending_products,
            title="Web Search References",
            caption=caption,
            rank_label="WEB RESULT",
        )

    show_trend(
        result
    )


def show_header():
    st.markdown(
        '<div class="brand">BEAUTYLENS</div>',
        unsafe_allow_html=True,
    )

    hero_html = textwrap.dedent(
        """
        <div class="hero-title">
            Find your next<br>
            <span>beauty favorite.</span>
        </div>
        <div class="hero-subtitle">
            피부 정보와 고민을 바탕으로 나에게 맞는 화장품을 찾아보세요.<br>
            성분 데이터, 개인화 추천 모델, 검색 트렌드와 웹 언급을 함께 분석합니다.
        </div>
        """
    ).strip()

    st.markdown(
        hero_html,
        unsafe_allow_html=True,
    )

    st.markdown(
        (
            '<div class="status-row">'
            '<div class="status-chip">Ingredient Search</div>'
            '<div class="status-chip">LightFM Personalization</div>'
            '<div class="status-chip">Google Trends</div>'
            '<div class="status-chip">LLM Assistant</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def initialize_state():
    defaults = {
        "messages": [],
        "pending_query": None,
        "pending_missing_fields": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "started" not in st.session_state:
        st.session_state.started = bool(
            st.session_state.messages
        )


def add_welcome_message():
    st.session_state.messages.append(
        {
            "role": "assistant",
            "data": {
                "type": "general_question",
                "answer": (
                    "**BeautyLens에 오신 것을 환영합니다.**\n\n"
                    "화장품 추천을 위해 알고 있는 정보만 "
                    "자유롭게 알려주세요.\n\n"
                    "- **피부 타입**: 지성, 건성, 복합성, 중성, 민감성\n"
                    "- **피부 고민**: 모공, 피지, 블랙헤드, 트러블, "
                    "속건조, 민감함, 홍조, 피부 장벽, 잡티, "
                    "주름, 탄력, 피부결 등\n"
                    "- **원하는 제품 종류**: 세럼, 앰플, 토너, "
                    "크림, 로션, 파운데이션, 쿠션, 컨실러 등\n"
                    "- **원하는 성분**: 알고 있다면 입력해 주세요. "
                    "모르는 경우 피부 타입과 고민을 바탕으로 "
                    "추천 성분을 선택합니다.\n"
                    "- **색조 제품의 경우**: 피부톤, 눈 색상, "
                    "머리 색상 등의 정보를 함께 입력할 수 있습니다.\n\n"
                    "모든 정보를 한 번에 입력하지 않아도 됩니다. "
                    "필요한 정보가 부족하면 제가 추가로 질문할게요."
                ),
                "result": {},
            },
        }
    )


def render_messages():
    for message in st.session_state.messages:
        if message["role"] == "user":
            user_html = (
                f'<div class="user-question">'
                f'{safe(message["content"])}'
                f'</div>'
            )

            st.markdown(
                user_html,
                unsafe_allow_html=True,
            )

        elif message["role"] == "assistant":
            show_result(
                message["data"]
            )


def get_chat_placeholder():
    missing_fields = (
        st.session_state.pending_missing_fields
    )

    if (
        st.session_state.pending_query
        and "product_type" in missing_fields
    ):
        return (
            "원하는 제품 종류를 입력하세요. "
            "예: 세럼, 크림, 파운데이션, 쿠션"
        )

    if (
        st.session_state.pending_query
        and "ingredient" in missing_fields
    ):
        return (
            "원하는 성분을 입력하세요. "
            "예: 히알루론산, 나이아신아마이드"
        )

    return "메시지를 입력하세요."


def build_api_message(user_input):
    if not st.session_state.pending_query:
        return user_input

    return (
        f"{st.session_state.pending_query}\n"
        f"추가 정보: {user_input}"
    )


def update_pending_state(
    data,
    api_message,
):
    response_type = data.get(
        "type"
    )
    result = (
        data.get("result")
        or {}
    )

    if response_type == "need_more_info":
        st.session_state.pending_query = (
            api_message
        )
        st.session_state.pending_missing_fields = (
            result.get(
                "missing_fields",
                [],
            )
            or []
        )
        return

    st.session_state.pending_query = None
    st.session_state.pending_missing_fields = []


def request_recommendation(
    api_message,
):
    response = requests.post(
        API_URL,
        json={
            "message": api_message
        },
        timeout=120,
    )

    if response.status_code == 200:
        return response.json()

    try:
        error_data = response.json()
        detail = error_data.get(
            "detail",
            "추천 요청에 실패했습니다.",
        )
    except ValueError:
        detail = (
            "추천 요청에 실패했습니다."
        )

    raise RuntimeError(
        detail
    )


def handle_user_input(user_input):
    st.session_state.messages.append(
        {
            "role": "user",
            "content": user_input,
        }
    )

    user_html = (
        f'<div class="user-question">'
        f'{safe(user_input)}'
        f'</div>'
    )
    st.markdown(
        user_html,
        unsafe_allow_html=True,
    )

    api_message = build_api_message(
        user_input
    )

    with st.spinner(
        "성분과 취향을 분석하고 있어요."
    ):
        try:
            data = request_recommendation(
                api_message
            )

        except requests.exceptions.ConnectionError:
            st.error(
                "추천 서버에 연결할 수 없습니다. "
                "FastAPI가 실행 중인지 확인해주세요."
            )
            return

        except requests.exceptions.Timeout:
            st.error(
                "추천 처리 시간이 너무 오래 걸렸습니다. "
                "잠시 후 다시 시도해주세요."
            )
            return

        except RuntimeError as error:
            st.error(
                str(error)
            )
            return

        except Exception as error:
            st.error(
                f"오류가 발생했습니다: {error}"
            )
            return

    update_pending_state(
        data,
        api_message,
    )

    show_result(
        data
    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "data": data,
        }
    )


def main():
    show_header()
    initialize_state()

    if not st.session_state.started:
        if st.button(
            "대화 시작하기",
            use_container_width=True,
        ):
            st.session_state.started = True
            add_welcome_message()
            st.rerun()

    render_messages()

    if not st.session_state.started:
        return

    user_input = st.chat_input(
        get_chat_placeholder()
    )

    if user_input:
        handle_user_input(
            user_input
        )


if __name__ == "__main__":
    main()

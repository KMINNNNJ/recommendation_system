from __future__ import annotations

import pandas as pd

from src.trends.google_trends_collector import (
    collect_google_trends,
)


HM_TREND_KEYWORDS = {
    "style": [
        "wide leg jeans",
        "cargo pants",
        "oversized blazer",
        "maxi skirt",
        "linen shirt",
    ],
    "category": [
        "women jeans",
        "women blazer",
        "women knitwear",
        "women dress",
        "women jacket",
    ],
    "brand": [
        "H&M fashion",
        "Zara fashion",
        "Uniqlo fashion",
        "Mango fashion",
        "COS fashion",
    ],
    "product": [
        "wide leg denim jeans",
        "cropped trench coat",
        "oversized leather jacket",
        "linen blend shirt",
        "ribbed knit dress",
    ],
}


def collect_hm_trends(
    entity_type: str,
    geo: str = "US",
    timeframe: str = "today 3-m",
) -> pd.DataFrame:
    """
    패션 스타일, 카테고리, 브랜드 또는 제품 트렌드를 수집한다.
    """

    if entity_type not in HM_TREND_KEYWORDS:
        allowed_types = list(HM_TREND_KEYWORDS.keys())

        raise ValueError(
            f"지원하지 않는 entity_type입니다: {entity_type}. "
            f"사용 가능 값: {allowed_types}"
        )

    keywords = HM_TREND_KEYWORDS[entity_type]

    trend_df = collect_google_trends(
        keywords=keywords,
        geo=geo,
        timeframe=timeframe,
        category=0,
    )

    trend_df["domain"] = "fashion"
    trend_df["entity_type"] = entity_type

    return trend_df


if __name__ == "__main__":
    result = collect_hm_trends(
        entity_type="style",
        geo="US",
        timeframe="today 3-m",
    )

    print(result.head(20))
    print()
    print("shape:", result.shape)
    print("keywords:", result["keyword"].unique().tolist())
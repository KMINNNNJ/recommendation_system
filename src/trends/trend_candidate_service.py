from typing import Any, Dict, List


BEAUTY_HINTS = [
    "스킨케어",
    "화장품",
    "세럼",
    "크림",
    "토너",
    "선크림",
    "립",
    "메이크업",
    "skincare",
    "serum",
    "cream",
    "beauty",
    "makeup",
]

FASHION_HINTS = [
    "패션",
    "청바지",
    "재킷",
    "원피스",
    "치마",
    "신발",
    "가방",
    "fashion",
    "jeans",
    "jacket",
    "dress",
    "shoes",
    "bag",
]


def classify_domain(keyword: str) -> str:
    normalized = keyword.lower().strip()

    if any(hint in normalized for hint in BEAUTY_HINTS):
        return "beauty"

    if any(hint in normalized for hint in FASHION_HINTS):
        return "fashion"

    return "other"


def filter_trend_candidates(
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result = []

    for row in rows:
        keyword = str(row.get("trend", "")).strip()

        if not keyword:
            continue

        domain = classify_domain(keyword)

        if domain == "other":
            continue

        item = dict(row)
        item["keyword"] = keyword
        item["domain"] = domain

        result.append(item)

    return result
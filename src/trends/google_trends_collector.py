#pytrend를 이용해 키워드를 가져오면 구글에서 비정상적인 트래픽을 감지하고 요청을 차단함
#429 에러가 나옴 . pytrend를 이용해 키워드를 가져오는건 실패
#pytrend는 현재 유지보수가 되고있지않기 때문에 해결불가로 알고있음
#그래서 pytrend 대용으로 나온 trendspyg를 사용함

from typing import Any, Dict, List

from trendspyg import download_google_trends_rss


def collect_trending_now(
    geo: str = "KR",
) -> List[Dict[str, Any]]:
    """
    Google Trending Now RSS에서 현재 급상승 검색어를 수집한다.
    """

    trends = download_google_trends_rss(geo)

    if not trends:
        return []

    return trends

from typing import Any, Dict, List

from trendspyg import (
    download_google_trends_csv,
    download_google_trends_rss,
)


def collect_trending_now_rss(
    geo: str = "KR",
) -> List[Dict[str, Any]]:
    return download_google_trends_rss(
        geo=geo,
        normalize=True,
    )["trends"]


def collect_category_trends(
    geo: str = "KR",
    category: str = "beauty",
    hours: int = 168,
) -> List[Dict[str, Any]]:
    """
    카테고리별 Trending Now 결과를 가져온다.

    hours:
        4   = 최근 4시간
        24  = 최근 24시간
        48  = 최근 48시간
        168 = 최근 7일
    """

    result_df = download_google_trends_csv(
        geo=geo,
        hours=hours,
        category=category,
        output_format="dataframe",
    )

    if result_df is None or result_df.empty:
        return []

    result_df["geo"] = geo
    result_df["category"] = category

    return result_df.to_dict(orient="records")


if __name__ == "__main__":
    rows = collect_category_trends(
        geo="KR",
        category="sports",
        hours=168,
    )

    print(f"수집 건수: {len(rows)}")

    for row in rows[:20]:
        print(row)
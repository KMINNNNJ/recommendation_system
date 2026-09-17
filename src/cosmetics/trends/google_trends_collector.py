import logging

from trendspyg import (
    download_google_trends_interest_over_time,
)
from trendspyg.exceptions import RateLimitError


logger = logging.getLogger(__name__)


def collect_keyword_trend(
    keyword,
    geo="KR",
    timeframe="today 12-m",
):
    keyword = str(
        keyword or ""
    ).strip()

    if not keyword:
        return []

    try:
        result = (
            download_google_trends_interest_over_time(
                keyword,
                geo=geo,
                timeframe=timeframe,
                cache="disk",
                cookies="disk",
            )
        )

    except RateLimitError:
        logger.warning(
            "Google Trends request was rate limited."
        )
        return []

    except TypeError as exc:
        if "cookies" in str(exc):
            raise RuntimeError(
                "현재 trendspyg 버전이 cookies='disk'를 "
                "지원하지 않습니다. "
                "pip install -U trendspyg 로 업데이트하세요."
            ) from exc

        raise

    except Exception as exc:
        logger.warning(
            "Google Trends request failed: %s",
            exc,
        )
        return []

    return result or []


def summarize_keyword_trend(
    rows,
    weeks=4,
):
    completed_rows = [
        row
        for row in rows
        if not row.get(
            "is_partial",
            False,
        )
    ]

    required_count = weeks * 2

    if len(completed_rows) < required_count:
        return None

    recent_rows = completed_rows[
        -weeks:
    ]
    previous_rows = completed_rows[
        -required_count:
        -weeks
    ]

    recent_values = [
        row["value"]
        for row in recent_rows
    ]
    previous_values = [
        row["value"]
        for row in previous_rows
    ]

    recent_average = (
        sum(recent_values)
        / len(recent_values)
    )
    previous_average = (
        sum(previous_values)
        / len(previous_values)
    )

    change_rate = None

    if previous_average != 0:
        change_rate = (
            (
                recent_average
                - previous_average
            )
            / previous_average
            * 100
        )

    latest_row = completed_rows[-1]
    peak_row = max(
        completed_rows,
        key=lambda row: row["value"],
    )

    has_recent_signal = any(
        float(value or 0) > 0
        for value in (
            recent_values
            + previous_values
        )
    )

    return {
        "recent_average": round(
            recent_average,
            2,
        ),
        "previous_average": round(
            previous_average,
            2,
        ),
        "change_rate": (
            round(
                change_rate,
                2,
            )
            if change_rate is not None
            else None
        ),
        "latest_value": latest_row["value"],
        "latest_date": latest_row["date"],
        "peak_value": peak_row["value"],
        "peak_date": peak_row["date"],
        "has_recent_signal": has_recent_signal,
        "comparison_weeks": int(weeks),
    }


def main():
    keyword = input(
        "검색할 성분을 입력하세요: "
    ).strip()

    rows = collect_keyword_trend(
        keyword=keyword,
        geo="KR",
        timeframe="today 12-m",
    )

    print(f"\n검색어: {keyword}")
    print(f"데이터 수: {len(rows)}")

    summary = summarize_keyword_trend(
        rows
    )

    if summary is None:
        print(
            "\n트렌드를 분석하기 위한 데이터가 부족하거나 "
            "Google Trends 요청이 제한되었습니다."
        )
        return

    print("\n[Google Trends 요약]")
    print(
        "최근 4주 평균: "
        f"{summary['recent_average']}"
    )
    print(
        "이전 4주 평균: "
        f"{summary['previous_average']}"
    )

    if summary["change_rate"] is not None:
        print(
            "변화율: "
            f"{summary['change_rate']}%"
        )

    print(
        "최근 관심도: "
        f"{summary['latest_value']} "
        f"({summary['latest_date']})"
    )
    print(
        "최근 12개월 최고 관심도: "
        f"{summary['peak_value']} "
        f"({summary['peak_date']})"
    )


if __name__ == "__main__":
    main()

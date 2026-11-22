from collections import Counter
import re
from typing import Mapping, Sequence

import pandas as pd


def find_related_news(
    target: dict,
    news_items: Sequence[dict],
    limit: int = 3,
) -> list[dict]:
    target_id = target.get("id")
    target_symbol = str(target.get("symbol") or "")
    target_event = str(target.get("event_type") or "")
    target_title = re.sub(r"[\W_]+", "", str(target.get("title") or "").casefold())

    scored = []
    for item in news_items:
        if item.get("id") == target_id:
            continue
        score = 0
        title_similarity = 0.0
        if target_symbol and str(item.get("symbol") or "") == target_symbol:
            score += 4
        if target_event and str(item.get("event_type") or "") == target_event:
            score += 3

        item_title = re.sub(
            r"[\W_]+",
            "",
            str(item.get("title") or "").casefold(),
        )
        if target_title and item_title:
            shared = set(target_title) & set(item_title)
            union = set(target_title) | set(item_title)
            title_similarity = len(shared) / len(union)
            score += title_similarity * 3

        if score >= 4 or title_similarity >= 0.45:
            scored.append((score, item))

    scored.sort(
        key=lambda pair: (
            pair[0],
            str(pair[1].get("publish_time") or ""),
            pair[1].get("id") or 0,
        ),
        reverse=True,
    )
    return [item for _, item in scored[:limit]]


def group_same_day_headlines(news_items: Sequence[dict]) -> list[list[dict]]:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for item in news_items:
        title = re.sub(r"[\W_]+", "", str(item.get("title") or "").casefold())
        publish_date = str(
            item.get("publish_time") or item.get("created_at") or ""
        )[:10]
        if not title or not publish_date:
            continue
        key = (
            str(item.get("symbol") or ""),
            title,
            publish_date,
        )
        groups.setdefault(key, []).append(item)

    return [
        group
        for group in groups.values()
        if len(
            {
                str(item.get("source") or item.get("url") or "")
                for item in group
            }
        )
        > 1
    ]


def build_daily_trend_data(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "日期": row["date"],
                "利好": row["positive"] or 0,
                "利空": row["negative"] or 0,
                "中性": row["neutral"] or 0,
                "较高影响": row["high_impact"] or 0,
            }
            for row in reversed(rows)
        ],
        columns=["日期", "利好", "利空", "中性", "较高影响"],
    )


def build_sentiment_chart_data(
    news_items: Sequence[dict], labels: Mapping[str, str]
) -> pd.DataFrame:
    counts = Counter(
        item.get("sentiment")
        for item in news_items
        if item.get("sentiment") in labels
    )
    return pd.DataFrame(
        {
            "情绪方向": [
                f"{label}（{counts.get(sentiment, 0)}）"
                for sentiment, label in labels.items()
            ],
            "新闻数": [counts.get(sentiment, 0) for sentiment in labels],
        }
    )


def build_export_data(
    news_items: Sequence[dict], columns: Mapping[str, str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                label: (
                    "；".join(item.get(field) or [])
                    if field in ("key_facts", "watch_items")
                    else item.get(field)
                )
                for label, field in columns.items()
            }
            for item in news_items
        ]
    )


def build_category_chart_data(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"类别": row["category"], "新闻数": row["total"]}
            for row in rows
        ],
        columns=["类别", "新闻数"],
    )


def build_category_detail_data(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "类别": row["category"],
                "新闻数": row["total"],
                "较高影响利空": row["high_impact_negative"],
            }
            for row in rows
        ],
        columns=["类别", "新闻数", "较高影响利空"],
    )


def build_source_health_data(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "来源": row["source"],
                "新闻数": row["total"],
                "已分析": row["analyzed"],
                "待分析": row["pending"],
                "分析失败": row["failed"],
                "最新新闻时间": row["latest_news_time"],
            }
            for row in rows
        ],
        columns=[
            "来源",
            "新闻数",
            "已分析",
            "待分析",
            "分析失败",
            "最新新闻时间",
        ],
    )

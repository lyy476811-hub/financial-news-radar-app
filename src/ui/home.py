from datetime import datetime, timedelta

import streamlit as st

from src.storage import (
    query_tracked_events,
    query_news,
    query_watch_items,
)
from src.ui.constants import SENTIMENT_LABELS


def _render_priority_news(news_items: list[dict]) -> None:
    st.subheader("优先关注")
    if not news_items:
        st.info("近 24 小时没有符合条件的新闻。")
        return

    priority_news = sorted(
        news_items,
        key=lambda item: (
            item.get("impact_score") or 0,
            item.get("sentiment") == "negative",
        ),
        reverse=True,
    )
    for item in priority_news[:5]:
        score = item.get("impact_score")
        sentiment = SENTIMENT_LABELS.get(item.get("sentiment"), "待分析")
        with st.container(border=True):
            st.caption(
                f"{item.get('symbol') or '市场'} · {sentiment} · "
                f"影响分 {score}/5" if score is not None
                else f"{item.get('symbol') or '市场'} · {sentiment} · 影响分待补"
            )
            st.write(item.get("title") or "无标题")
            st.caption(
                f"{item.get('publish_time') or '时间未知'} · "
                f"{item.get('source') or '来源未知'} · "
                f"{item.get('event_type') or '事件未分类'}"
            )
            if item.get("impact_path"):
                st.write(item["impact_path"])
            url = item.get("url") or ""
            if url.startswith(("http://", "https://")):
                st.link_button(
                    "查看原文",
                    url,
                    key=f"brief_news_link_{item['id']}",
                )


def _render_tracking_snapshot() -> None:
    st.subheader("跟踪与待核实")
    tracked_events = query_tracked_events(status="tracking", limit=5)
    if tracked_events:
        st.markdown("**持续跟踪的事件**")
        for event in tracked_events:
            st.write(
                f"{event.get('symbol') or '市场'} · "
                f"{event.get('title') or '无标题'}"
            )
            st.caption(
                f"{event.get('event_type') or '未分类'} · "
                f"{event['followup_count']} 条后续报道"
            )
    else:
        st.info("暂无持续跟踪的事件。")

    pending_items = query_watch_items(status="pending", limit=5)
    if pending_items:
        st.markdown("**待核实事项**")
        for item in pending_items:
            st.write(item["watch_item"])
            st.caption(item.get("title") or "无标题")
    else:
        st.caption("暂无待核实事项。")


def render_today_brief(stats: dict) -> None:
    now = datetime.now()
    since = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    recent_news = query_news(since=since, limit=50)
    high_impact = [
        item
        for item in recent_news
        if (item.get("impact_score") or 0) >= 4
    ]
    tracking_count = len(query_tracked_events(status="tracking", limit=500))

    st.subheader("今日简报")
    st.caption(
        f"近 24 小时新闻 · 更新时间 {now.strftime('%Y-%m-%d %H:%M')} · "
        "影响分表示潜在重要性，不代表股价涨跌"
    )
    with st.container(horizontal=True):
        st.metric("近 24 小时新闻", len(recent_news), border=True)
        st.metric("较高影响新闻", len(high_impact), border=True)
        st.metric("待补分析", stats["needs_analysis"], border=True)
        st.metric("持续跟踪事件", tracking_count, border=True)

    if len(recent_news) == 50:
        st.caption("近 24 小时新闻展示上限为 50 条。")

    left, right = st.columns([1.7, 1], gap="large")
    with left:
        _render_priority_news(recent_news)
    with right:
        _render_tracking_snapshot()

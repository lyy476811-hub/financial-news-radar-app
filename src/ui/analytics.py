import streamlit as st

from src.dashboard import (
    build_category_chart_data,
    build_category_detail_data,
    build_daily_trend_data,
    build_source_health_data,
    group_same_day_headlines,
)
from src.storage import (
    get_daily_analytics,
    get_event_category_stats,
    get_source_health,
    get_source_news_preview,
)
from src.ui.constants import SENTIMENT_LABELS


def render_news_timeline(news_items: list[dict]) -> None:
    st.subheader("个股事件时间线")
    st.caption("按当前筛选结果展示；时间线基于新闻发布时间。")
    grouped_by_symbol: dict[str, list[dict]] = {}
    for item in news_items:
        symbol = item.get("symbol") or "未标注股票"
        grouped_by_symbol.setdefault(symbol, []).append(item)

    if not grouped_by_symbol:
        st.info("当前筛选没有可展示的新闻。")
        return

    for symbol, items in grouped_by_symbol.items():
        with st.container(border=True):
            st.markdown(f"**{symbol} · {len(items)} 条**")
            for item in items:
                st.write(
                    f"{item.get('publish_time') or '时间未知'} · "
                    f"{item.get('event_type') or '待分类'} · "
                    f"{item.get('title') or '无标题'}"
                )
                st.caption(
                    f"{item.get('source') or '来源未知'} · "
                    f"{SENTIMENT_LABELS.get(item.get('sentiment'), '待分析')} · "
                    f"影响分数 {item.get('impact_score') or '未知'}"
                )


def render_multi_source_events(news_items: list[dict]) -> None:
    st.subheader("同日同题多源报道")
    st.caption("只聚合同一股票、同一天、规范化标题相同且来源不同的报道。")
    groups = group_same_day_headlines(news_items)
    if not groups:
        st.info("当前筛选没有发现同日同题的多来源报道。")
        return

    for group in groups:
        title = group[0].get("title") or "无标题"
        symbol = group[0].get("symbol") or "未标注股票"
        sources = {
            str(item.get("source") or item.get("url") or "来源未知")
            for item in group
        }
        with st.expander(f"{symbol} · {title}（{len(sources)} 个来源）"):
            for item in group:
                st.caption(
                    f"{item.get('source') or '来源未知'} · "
                    f"{item.get('publish_time') or '时间未知'}"
                )
                url = item.get("url") or ""
                if url.startswith(("http://", "https://")):
                    st.link_button(
                        "查看该来源原文",
                        url,
                        icon=":material/open_in_new:",
                    )


def _render_trend_overview() -> None:
    st.subheader("新闻与情绪趋势")
    st.caption("按新闻发布时间统计，不代表来源可信度或交易结果。")
    period = st.segmented_control(
        "统计周期",
        options=["近7天", "近30天", "近90天"],
        default="近30天",
        key="analytics_trend_period",
        width="stretch",
    )
    days = {"近7天": 7, "近30天": 30, "近90天": 90}[period]
    rows = get_daily_analytics(days)
    if not rows:
        st.info("所选周期内没有新闻数据。")
        return

    trend_data = build_daily_trend_data(rows)
    left, right = st.columns([3, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**情绪与新闻量趋势**")
            st.line_chart(trend_data, x="日期", y=["利好", "利空", "中性"])
    with right:
        with st.container(border=True):
            st.markdown("**较高影响趋势**")
            st.line_chart(trend_data, x="日期", y="较高影响")

    st.dataframe(trend_data, hide_index=True, width="stretch")


def _render_event_overview() -> None:
    st.subheader("事件类型与影响范围")
    st.caption("统计全库已保存新闻；较高影响利空计数仅代表模型标注结果。")
    summaries = get_event_category_stats()
    event_types = summaries["event_type"]
    affected_scopes = summaries["affected_scope"]
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**事件类型分布**")
            if event_types:
                st.bar_chart(
                    build_category_chart_data(event_types),
                    x="类别",
                    y="新闻数",
                )
                st.dataframe(
                    build_category_detail_data(event_types),
                    hide_index=True,
                )
            else:
                st.info("暂无可统计的事件类型。")
    with right:
        with st.container(border=True):
            st.markdown("**影响范围分布**")
            if affected_scopes:
                st.bar_chart(
                    build_category_chart_data(affected_scopes),
                    x="类别",
                    y="新闻数",
                )
            else:
                st.info("暂无可统计的影响范围。")


def _render_source_overview() -> None:
    st.subheader("来源数据概况")
    st.caption(
        "按来源统计已入库新闻和分析状态；这不代表来源权威性，也不表示抓取服务当前可用。"
    )
    source_rows = get_source_health()
    if not source_rows:
        st.info("数据库中还没有来源数据。")
        return
    st.dataframe(build_source_health_data(source_rows), hide_index=True)
    source_names = [row["source"] for row in source_rows]
    selected_source = st.selectbox(
        "下钻查看来源近期新闻",
        options=source_names,
        key="analytics_source_drilldown",
    )
    preview = get_source_news_preview(selected_source, limit=20)
    if preview:
        with st.container(border=True):
            st.markdown(f"**{selected_source} · 近期新闻**")
            for item in preview:
                st.markdown(
                    f"- {item.get('publish_time') or '时间未知'} · "
                    f"{SENTIMENT_LABELS.get(item.get('sentiment'), '待分析')} · "
                    f"{item.get('impact_score') or '—'}/5 · "
                    f"{item.get('title') or '无标题'}"
                )


def render_analytics_workspace() -> None:
    selected_view = st.segmented_control(
        "数据视图",
        options=["趋势概览", "事件分布", "来源概况"],
        key="analytics_view",
        width="stretch",
    )
    if selected_view == "来源概况":
        _render_source_overview()
    elif selected_view == "趋势概览":
        _render_trend_overview()
    else:
        _render_event_overview()

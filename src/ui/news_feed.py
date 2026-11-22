import streamlit as st

from src.dashboard import (
    build_export_data,
    build_sentiment_chart_data,
    find_related_news,
)
from src.storage import query_analysis_feedback, save_analysis_feedback
from src.ui.constants import (
    SENTIMENT_ICONS,
    SENTIMENT_LABELS,
    TIME_HORIZON_LABELS,
)


def render_news_feed(news_items: list[dict]) -> None:
    st.subheader("新闻流")
    st.caption("展开新闻可查看事实、引用依据和分析细节。")
    feedback_by_news_id = query_analysis_feedback(
        [item["id"] for item in news_items if item.get("id") is not None]
    )
    completed_news = [item for item in news_items if item.get("sentiment")]
    high_impact_news = [
        item for item in completed_news if (item.get("impact_score") or 0) >= 4
    ]
    negative_high_impact = [
        item for item in high_impact_news if item.get("sentiment") == "negative"
    ]

    with st.container(horizontal=True):
        st.metric("筛选结果", len(news_items), border=True)
        st.metric("较高影响（4–5 分）", len(high_impact_news), border=True)
        st.metric("较高影响利空", len(negative_high_impact), border=True)
    st.caption("摘要依据筛选结果生成；影响分数是重要性判断，不代表股价涨跌幅。")

    if high_impact_news:
        for item in high_impact_news[:3]:
            st.write(
                f"{item.get('event_type') or '事件'} · "
                f"{item.get('title') or '无标题'} · "
                f"{SENTIMENT_LABELS.get(item.get('sentiment'), '未知')} · "
                f"{item.get('impact_score')}/5"
            )

    if not news_items:
        st.info("没有符合条件的新闻。可调整筛选条件或抓取新内容。")
        return

    export_columns = {
        "股票代码": "symbol",
        "标题": "title",
        "发布时间": "publish_time",
        "来源": "source",
        "情绪": "sentiment",
        "影响分数": "impact_score",
        "事件类型": "event_type",
        "影响范围": "affected_scope",
        "判断依据": "reason",
        "影响路径": "impact_path",
        "新闻事实": "key_facts",
        "原文引用": "evidence_quotes",
        "后续观察": "watch_items",
        "置信度": "confidence",
        "原文链接": "url",
    }
    export_data = build_export_data(news_items, export_columns)
    chart_data = build_sentiment_chart_data(news_items, SENTIMENT_LABELS)
    chart_col, export_col = st.columns([3, 1], gap="large")
    with chart_col:
        with st.container(border=True):
            st.subheader("筛选结果情绪分布")
            st.bar_chart(chart_data, x="情绪方向", y="新闻数")
    with export_col:
        with st.container(border=True):
            st.subheader("数据导出")
            st.caption(f"可导出筛选出的 {len(news_items)} 条完整分析记录。")
            st.download_button(
                "导出筛选结果 CSV",
                data=export_data.to_csv(index=False).encode("utf-8-sig"),
                file_name="financial_news_radar.csv",
                mime="text/csv",
                icon=":material/download:",
                width="stretch",
            )

    for item in news_items:
        title = item.get("title") or "无标题"
        sentiment = item.get("sentiment")
        score = item.get("impact_score")
        if item.get("analysis_error"):
            heading = f"待处理 · {title[:60]}"
        elif sentiment and score is None:
            heading = (
                f"待补充影响分 · {SENTIMENT_LABELS.get(sentiment, '未知')} · "
                f"{title[:60]}"
            )
        elif sentiment:
            heading = (
                f"{SENTIMENT_ICONS.get(sentiment, '')} "
                f"{SENTIMENT_LABELS.get(sentiment, '未知')} · "
                f"{score}/5 · {title[:60]}"
            )
        else:
            heading = f"待分析 · {title[:60]}"

        with st.expander(heading):
            st.write(title)
            published = item.get("publish_time") or item.get("created_at") or "时间未知"
            source = item.get("source") or "来源未知"
            news_symbol = item.get("symbol") or "旧数据未记录"
            st.caption(
                f"股票代码：{news_symbol} · 来源：{source} · 时间：{published}"
            )

            url = item.get("url") or ""
            if url.startswith(("http://", "https://")):
                st.link_button(
                    "查看原文",
                    url,
                    icon=":material/open_in_new:",
                )

            if item.get("analysis_error"):
                st.error(f"分析失败：{item['analysis_error']}")
                continue
            if not sentiment:
                st.info("该新闻尚未完成分析。")
                continue

            details = st.columns(4)
            details[0].metric(
                "影响分数",
                f"{score}/5" if score is not None else "待补分析",
            )
            details[1].metric("事件类型", item.get("event_type") or "未标注")
            details[2].metric("影响范围", item.get("affected_scope") or "未判断")
            details[3].metric(
                "影响时间",
                TIME_HORIZON_LABELS.get(item.get("time_horizon"), "暂不明确"),
            )

            analysis_col, path_col = st.columns(2, gap="large")
            with analysis_col:
                with st.container(border=True):
                    st.markdown("**判断依据**")
                    st.write(item.get("reason") or "暂无")
            with path_col:
                with st.container(border=True):
                    st.markdown("**潜在影响路径**")
                    st.write(item.get("impact_path") or "暂无")

            facts = item.get("key_facts") or []
            if facts:
                with st.container(border=True):
                    st.markdown("**新闻明确披露的事实**")
                    for fact in facts:
                        st.markdown(f"- {fact}")

            evidence_quotes = item.get("evidence_quotes")
            if evidence_quotes:
                with st.container(border=True):
                    st.markdown("**原文引用依据**")
                    st.caption("以下引用来自新闻原文，已逐字保留。")
                    for quote in evidence_quotes:
                        st.markdown(f"> {quote}")
            elif evidence_quotes is None:
                with st.container(border=True):
                    st.markdown("**原文引用依据**")
                    st.caption("旧版分析尚无原文引用，可通过“补充旧新闻分析”更新。")
            else:
                with st.container(border=True):
                    st.markdown("**原文引用依据**")
                    st.caption("未找到可逐字匹配的原文引用。")

            watch_items = item.get("watch_items") or []
            if watch_items:
                with st.container(border=True):
                    st.markdown("**后续值得核实**")
                    for watch_item in watch_items:
                        st.markdown(f"- {watch_item}")

            related_news = find_related_news(item, news_items, limit=3)
            if related_news:
                with st.container(border=True):
                    st.markdown("**相似及相关新闻**")
                    for related in related_news:
                        st.markdown(
                            f"- {related.get('publish_time') or '时间未知'} · "
                            f"{related.get('source') or '来源未知'} · "
                            f"{related.get('title') or '无标题'}"
                        )
                        related_url = related.get("url") or ""
                        if related_url.startswith(("http://", "https://")):
                            st.link_button(
                                "查看相关新闻",
                                related_url,
                                key=(
                                    f"related_news_link_{item.get('id', 'unknown')}_"
                                    f"{related.get('id', 'unknown')}"
                                ),
                                icon=":material/open_in_new:",
                            )

            confidence = item.get("confidence")
            if confidence is not None:
                st.progress(
                    confidence / 100,
                    text=f"模型判断置信度：{confidence}%",
                )
            analyzed_at = item.get("analyzed_at") or "未知"
            model = item.get("analysis_model") or "未知"
            st.caption(f"分析时间：{analyzed_at} · 模型：{model}")
            feedback = feedback_by_news_id.get(item.get("id"))
            if feedback:
                rating_label = (
                    "基本合理"
                    if feedback["rating"] == "reasonable"
                    else "需要修正"
                )
                correction = (
                    f" · 人工建议 {feedback['corrected_score']}/5"
                    if feedback.get("corrected_score") is not None
                    else ""
                )
                st.caption(f"人工复核：{rating_label}{correction}")

    feedback_candidates = [
        item
        for item in news_items
        if item.get("id") is not None
        and item.get("sentiment")
        and not item.get("analysis_error")
    ]
    if feedback_candidates:
        candidate_by_id = {item["id"]: item for item in feedback_candidates}
        candidate_ids = list(candidate_by_id)
        if st.session_state.get("analysis_feedback_news_id") not in candidate_ids:
            st.session_state["analysis_feedback_news_id"] = candidate_ids[0]

        st.divider()
        st.subheader("人工复核")
        st.caption("反馈会单独保存，不会自动改写 AI 分析或影响分数。")
        selected_news_id = st.selectbox(
            "选择要复核的新闻",
            options=candidate_ids,
            format_func=lambda news_id: candidate_by_id[news_id]["title"],
            key="analysis_feedback_news_id",
        )
        current_feedback = feedback_by_news_id.get(selected_news_id, {})
        current_rating = current_feedback.get("rating", "")
        current_score = current_feedback.get("corrected_score")
        rating_options = ["", "reasonable", "needs_revision"]
        score_options = ["", "1", "2", "3", "4", "5"]
        with st.form("analysis_feedback_form"):
            rating = st.selectbox(
                "分析判断",
                options=rating_options,
                index=rating_options.index(current_rating),
                format_func=lambda value: {
                    "": "请选择",
                    "reasonable": "基本合理",
                    "needs_revision": "需要修正",
                }[value],
                key="analysis_feedback_rating",
            )
            corrected_score = st.selectbox(
                "建议影响分（可选）",
                options=score_options,
                index=(
                    score_options.index(str(current_score))
                    if current_score is not None
                    else 0
                ),
                format_func=lambda value: value or "不提供",
                key="analysis_feedback_score",
            )
            comment = st.text_area(
                "复核说明",
                value=current_feedback.get("comment", ""),
                max_chars=500,
                key="analysis_feedback_comment",
            )
            submitted = st.form_submit_button(
                "保存复核",
                icon=":material/save:",
                key="submit_analysis_feedback",
            )

        if submitted:
            if not rating:
                st.warning("请选择分析判断。")
            elif rating == "reasonable" and corrected_score:
                st.warning("判断基本合理时，请将建议影响分设为“不提供”。")
            else:
                save_analysis_feedback(
                    selected_news_id,
                    rating,
                    int(corrected_score) if corrected_score else None,
                    comment,
                )
                st.success("人工复核已保存，AI 原始分析保持不变。")

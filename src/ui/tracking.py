import streamlit as st

from src.storage import (
    link_event_followup,
    query_event_status_history,
    query_event_followup_candidates,
    query_event_followups,
    query_news,
    query_tracked_events,
    query_watch_items,
    set_event_tracking_status,
    set_events_tracking_status,
    set_watch_item_status,
    set_watch_items_status,
    start_event_tracking,
)
from src.ui.constants import EVENT_STATUS_LABELS, WATCH_STATUS_LABELS


def _save_watch_status(news_id: int, item_index: int, widget_key: str) -> None:
    set_watch_item_status(
        news_id,
        item_index,
        st.session_state[widget_key],
    )


def _render_watch_tracker() -> None:
    st.subheader("待核实事项")
    st.caption("状态会保存到本地数据库；当前状态下显示全部跟踪事项。")
    with st.container(border=True):
        st.markdown("**筛选事项**")
        selected_status = st.selectbox(
            "事项状态",
            options=[*WATCH_STATUS_LABELS, "all"],
            format_func=lambda value: (
                "全部状态" if value == "all" else WATCH_STATUS_LABELS[value]
            ),
            key="watch_status_filter",
        )
        search_keyword = st.text_input(
            "搜索事项、标题或股票代码",
            key="watch_item_search",
            placeholder="输入关键词",
        )

    watch_items = query_watch_items(
        status=None if selected_status == "all" else selected_status,
        limit=None,
        search=search_keyword,
    )
    if not watch_items:
        status_label = (
            "全部状态"
            if selected_status == "all"
            else WATCH_STATUS_LABELS[selected_status]
        )
        st.info(f"没有状态为“{status_label}”且符合筛选条件的事项。")
        return

    item_options = [
        (item["news_id"], item["item_index"])
        for item in watch_items
    ]
    item_by_key = {
        key: item
        for key, item in zip(item_options, watch_items)
    }
    with st.container(border=True):
        st.markdown("**批量标记事项**")
        batch_items = st.multiselect(
            "选择事项",
            options=item_options,
            format_func=lambda key: (
                f"{item_by_key[key].get('symbol') or '市场'} · "
                f"{item_by_key[key]['watch_item']}"
            ),
            key="batch_watch_items",
        )
        batch_status = st.selectbox(
            "批量状态",
            options=list(WATCH_STATUS_LABELS),
            format_func=lambda value: WATCH_STATUS_LABELS[value],
            key="batch_watch_status",
        )
        if st.button(
            "批量保存",
            key="batch_save_watch_items",
            icon=":material/save:",
            disabled=not batch_items,
            width="stretch",
        ):
            updated = set_watch_items_status(batch_items, batch_status)
            st.success(f"已更新 {updated} 个待核实事项。")
            st.rerun()

    for item in watch_items:
        with st.container(border=True):
            st.markdown(f"**{item['watch_item']}**")
            st.caption(
                f"{item.get('symbol') or '市场'} · "
                f"{item.get('title') or '无标题'} · "
                f"{item.get('source') or '来源未知'} · "
                f"{item.get('publish_time') or '时间未知'}"
            )
            url = item.get("url") or ""
            if url.startswith(("http://", "https://")):
                st.link_button(
                    "查看相关原文",
                    url,
                    icon=":material/open_in_new:",
                )

            news_id = item["news_id"]
            item_index = item["item_index"]
            widget_key = f"watch_status_{news_id}_{item_index}"
            st.selectbox(
                "跟踪状态",
                options=list(WATCH_STATUS_LABELS),
                index=list(WATCH_STATUS_LABELS).index(item["status"]),
                format_func=lambda value: WATCH_STATUS_LABELS[value],
                key=widget_key,
                on_change=_save_watch_status,
                args=(news_id, item_index, widget_key),
            )



def _render_event_tracker() -> None:
    st.subheader("事件跟踪与复盘")
    st.caption(
        "选择已分析新闻作为事件起点；后续报道按股票、事件类型和时间筛选，"
        "关联前由你确认。"
    )

    tracked_events = query_tracked_events(limit=500)
    tracked_ids = {event["event_news_id"] for event in tracked_events}
    untracked_news = [
        item
        for item in query_news(analyzed_only=True, limit=500)
        if item["id"] not in tracked_ids
    ]
    if untracked_news:
        news_by_id = {item["id"]: item for item in untracked_news}
        with st.form("start_event_tracking_form"):
            event_news_id = st.selectbox(
                "选择事件起点",
                options=list(news_by_id),
                format_func=lambda news_id: news_by_id[news_id]["title"],
                key="event_start_news",
            )
            start_tracking = st.form_submit_button(
                "加入事件跟踪",
                icon=":material/add_task:",
                key="start_event_tracking_submit",
            )
        if start_tracking:
            start_event_tracking(event_news_id)
            st.rerun()
    else:
        st.info("没有尚未加入跟踪的已分析新闻。")

    tracked_events = query_tracked_events(limit=500)
    if not tracked_events:
        st.info("暂无跟踪中的事件。")
        return

    events_by_id = {event["event_news_id"]: event for event in tracked_events}
    with st.container(border=True):
        st.markdown("**批量更新事件状态**")
        batch_event_ids = st.multiselect(
            "选择事件",
            options=list(events_by_id),
            format_func=lambda event_id: events_by_id[event_id]["title"],
            key="batch_tracked_event_ids",
        )
        batch_status = st.selectbox(
            "统一状态",
            options=list(EVENT_STATUS_LABELS),
            format_func=lambda value: EVENT_STATUS_LABELS[value],
            key="batch_tracked_event_status",
        )
        batch_outcome = st.text_area(
            "统一结论（可选）",
            max_chars=500,
            key="batch_tracked_event_outcome",
        )
        if st.button(
            "批量保存",
            icon=":material/save:",
            key="batch_save_tracked_events",
            disabled=not batch_event_ids,
            width="stretch",
        ):
            updated = set_events_tracking_status(
                batch_event_ids,
                batch_status,
                batch_outcome,
            )
            st.success(f"已更新 {updated} 个跟踪事件。")
            st.rerun()

    selected_event_id = st.selectbox(
        "选择跟踪事件",
        options=list(events_by_id),
        format_func=lambda event_id: events_by_id[event_id]["title"],
        key="selected_tracked_event",
    )
    event = events_by_id[selected_event_id]
    with st.container(border=True):
        st.markdown(f"**事件起点：{event['title']}**")
        st.caption(
            f"{event.get('symbol') or '未记录股票代码'} · "
            f"{event.get('event_type') or '未分类'} · "
            f"{event.get('publish_time') or '时间未知'} · "
            f"已关联 {event['followup_count']} 条后续报道"
        )
        source_url = event.get("url") or ""
        if source_url.startswith(("http://", "https://")):
            st.link_button(
                "查看事件起点原文",
                source_url,
                icon=":material/open_in_new:",
            )

        with st.form(f"event_status_form_{selected_event_id}"):
            status = st.selectbox(
                "事件状态",
                options=list(EVENT_STATUS_LABELS),
                index=list(EVENT_STATUS_LABELS).index(event["status"]),
                format_func=lambda value: EVENT_STATUS_LABELS[value],
                key=f"event_status_{selected_event_id}",
            )
            outcome = st.text_area(
                "当前结论",
                value=event.get("outcome") or "",
                max_chars=500,
                key=f"event_outcome_{selected_event_id}",
            )
            update_event = st.form_submit_button(
                "保存事件状态",
                icon=":material/save:",
                key=f"save_event_status_{selected_event_id}",
            )
        if update_event:
            set_event_tracking_status(selected_event_id, status, outcome)
            st.rerun()

        if event.get("outcome"):
            st.markdown(f"**当前结论：** {event['outcome']}")

        history = query_event_status_history(selected_event_id)
        if history:
            with st.expander("事件状态与结论时间线", expanded=False):
                for record in history:
                    st.markdown(
                        f"- {record['changed_at']} · "
                        f"{EVENT_STATUS_LABELS.get(record['status'], record['status'])}"
                    )
                    if record.get("outcome"):
                        st.caption(record["outcome"])

        followups = query_event_followups(selected_event_id)
        st.markdown("**已确认关联的后续报道**")
        if followups:
            for followup in followups:
                st.markdown(
                    f"- {followup.get('publish_time') or '时间未知'} · "
                    f"{followup.get('source') or '来源未知'} · "
                    f"{followup['title']}"
                )
                url = followup.get("url") or ""
                if url.startswith(("http://", "https://")):
                    st.link_button(
                        f"查看后续报道 · {followup['id']}",
                        url,
                        key=f"event_followup_link_{followup['id']}",
                    )
        else:
            st.caption("尚未关联后续报道。")

        candidates = query_event_followup_candidates(selected_event_id, limit=30)
        if candidates:
            candidates_by_id = {item["id"]: item for item in candidates}
            with st.form(f"event_followup_form_{selected_event_id}"):
                followup_news_id = st.selectbox(
                    "候选后续新闻",
                    options=list(candidates_by_id),
                    format_func=lambda news_id: (
                        f"{candidates_by_id[news_id].get('publish_time') or '时间未知'} · "
                        f"{candidates_by_id[news_id]['title']}"
                    ),
                    key=f"event_followup_candidate_{selected_event_id}",
                )
                link_followup = st.form_submit_button(
                    "确认关联",
                    icon=":material/link:",
                    key=f"link_event_followup_submit_{selected_event_id}",
                )
            if link_followup:
                link_event_followup(selected_event_id, followup_news_id)
                st.rerun()
        elif not event.get("symbol"):
            st.info("事件起点未记录股票代码，无法筛选后续报道候选项。")
        else:
            st.caption("暂时没有符合股票、事件类型和时间条件的候选报道。")


def render_tracking_workspace() -> None:
    selected_view = st.segmented_control(
        "跟踪工作台",
        options=["事件跟踪", "待核实事项"],
        key="tracking_view",
        width="stretch",
    )
    if selected_view == "待核实事项":
        _render_watch_tracker()
    else:
        _render_event_tracker()

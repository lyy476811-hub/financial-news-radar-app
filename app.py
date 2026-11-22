from datetime import date, datetime, timedelta
import sqlite3
from time import monotonic

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.ai_analyzer import IMPACT_SCORE_RUBRIC, analyze_news_sentiment
from src.news_fetcher import (
    fetch_watchlist_news,
    parse_rss_urls,
    parse_watchlist,
)
from src.storage import (
    create_database_backup,
    get_analyzed_news_keys,
    get_named_presets,
    get_news_filter_options,
    get_scheduler_config,
    get_stats,
    get_watchlist_preferences,
    init_db,
    query_news,
    query_news_needing_analysis,
    save_named_presets,
    save_scheduler_config,
    save_watchlist_preferences,
    save_news,
    restore_database_backup,
)
from src.ui.analytics import (
    render_analytics_workspace,
    render_multi_source_events,
    render_news_timeline,
)
from src.ui.constants import (
    LEGACY_RSS_PRESETS,
    RSS_CATALOG,
    STOCK_CATALOG,
)
from src.ui.home import render_today_brief
from src.ui.news_feed import render_news_feed
from src.ui.tracking import render_tracking_workspace


def _analyze_batch(
    news_items: list[dict], fallback_symbol: str, label: str
) -> list[dict]:
    results = []
    started_at = monotonic()
    with st.status(label, expanded=True) as task_status:
        progress = st.progress(0)
        try:
            for index, news in enumerate(news_items):
                title = news.get("title") or "无标题"
                symbol = news.get("symbol") or fallback_symbol
                elapsed = monotonic() - started_at
                progress.progress(
                    (index + 1) / len(news_items),
                    text=(
                        f"分析中（{index + 1}/{len(news_items)}）："
                        f"{title[:35]} · 已用时 {elapsed:.0f} 秒"
                    ),
                )
                analysis = analyze_news_sentiment(news, symbol=symbol)
                results.append({**news, "symbol": symbol, **analysis})
        except Exception:
            task_status.update(
                label="分析意外中断；尚未写入本批结果。",
                state="error",
                expanded=True,
            )
            raise
        finally:
            progress.empty()

        failed = sum("error" in item for item in results)
        task_status.update(
            label=(
                f"分析完成：共 {len(results)} 条，失败 {failed} 条，"
                f"用时 {monotonic() - started_at:.1f} 秒。"
            ),
            state="complete",
            expanded=False,
        )
    return results


st.set_page_config(
    page_title="金融新闻雷达",
    page_icon="📡",
    layout="wide",
)

st.html(
    """
    <style>
    :root {
        --radar-bg: #080d18;
        --radar-panel: #111827;
        --radar-panel-soft: #0d1525;
        --radar-border: rgba(148, 163, 184, 0.16);
        --radar-text: #e5edf7;
        --radar-muted: #98a6ba;
        --radar-accent: #ff5a4f;
    }

    html, body, [class*="css"] {
        font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    }

    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 78% -10%, rgba(56, 189, 248, 0.08), transparent 28rem),
            linear-gradient(180deg, #0b1120 0%, var(--radar-bg) 100%);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111827 0%, #0b1220 100%);
        border-right: 1px solid var(--radar-border);
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.55rem;
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        line-height: 1.45;
    }

    [data-testid="stSidebar"] [data-testid="stHeader"] {
        border-bottom: 1px solid var(--radar-border);
        padding-bottom: 0.55rem;
    }

    [data-testid="stSidebar"] textarea {
        min-height: 72px !important;
        border-radius: 12px !important;
        font-family: "Microsoft YaHei", "Consolas", sans-serif;
        background: #0b1220 !important;
        border: 1px solid #384358 !important;
        box-shadow: none !important;
    }

    [data-testid="stSidebar"] textarea:focus {
        border-color: #ff3b30 !important;
        box-shadow: 0 0 0 1px rgba(255, 59, 48, 0.75) !important;
    }

    [data-testid="stSidebar"] [data-testid="stTab"] {
        border-radius: 8px 8px 0 0;
    }

    [data-testid="stSidebar"] [data-testid="stButton"] button,
    [data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
        border-radius: 11px;
        min-height: 44px;
    }

    [data-testid="stMainBlockContainer"] {
        max-width: 1360px;
        padding-top: 1.35rem;
        padding-bottom: 3.5rem;
    }

    [data-testid="stSegmentedControl"] {
        border-radius: 12px;
        background: rgba(17, 24, 39, 0.72);
        border: 1px solid var(--radar-border);
        padding: 4px;
    }

    [data-testid="stMetric"] {
        border-radius: 14px;
        background: linear-gradient(145deg, rgba(17, 24, 39, 0.94), rgba(13, 21, 37, 0.94));
        border: 1px solid var(--radar-border);
        padding: 0.85rem 1rem;
        box-shadow: 0 10px 28px rgba(2, 6, 23, 0.14);
    }

    [data-testid="stExpander"] {
        border-radius: 12px;
        border-color: var(--radar-border);
        background: rgba(17, 24, 39, 0.38);
        overflow: hidden;
    }

    [data-testid="stContainer"][data-stylable="true"],
    [data-testid="stContainer"]:has([data-testid="stMarkdownContainer"]) {
        border-radius: 14px;
    }

    [data-testid="stDownloadButton"] button,
    [data-testid="stLinkButton"] a,
    [data-testid="stButton"] button {
        border-radius: 10px;
    }

    [data-testid="stForm"] {
        border-radius: 14px;
    }

    [data-testid="stSubheader"] {
        margin-top: 0.15rem;
    }

    [data-testid="stCaptionContainer"] {
        color: var(--radar-muted);
    }

    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stSelectbox"] div,
    [data-testid="stMultiSelect"] div {
        transition: border-color 120ms ease, box-shadow 120ms ease;
    }

    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus {
        border-color: var(--radar-accent) !important;
        box-shadow: 0 0 0 1px rgba(255, 90, 79, 0.45) !important;
    }

    @media (max-width: 900px) {
        [data-testid="stMainBlockContainer"] {
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }
    </style>
    """
)

st.session_state.setdefault("news_filter_signature", None)
st.session_state.setdefault("news_list_include_failed", True)
st.session_state.setdefault("news_list_keyword", "")
st.session_state.setdefault("last_fetch_status", None)
st.session_state.setdefault("last_scheduled_fetch_at", None)

BUILT_IN_FILTER_PRESETS = {
    "近24小时": {
        "date_range": "近24小时",
        "custom_dates": [],
        "include_failed": True,
        "keyword": "",
        "symbols": [],
        "sources": [],
        "sentiments": ["positive", "negative", "neutral"],
        "min_impact": 1,
    },
    "近7天": {
        "date_range": "近7天",
        "custom_dates": [],
        "include_failed": True,
        "keyword": "",
        "symbols": [],
        "sources": [],
        "sentiments": ["positive", "negative", "neutral"],
        "min_impact": 1,
    },
    "较高影响利空": {
        "date_range": "全部时间",
        "custom_dates": [],
        "include_failed": True,
        "keyword": "",
        "symbols": [],
        "sources": [],
        "sentiments": ["negative"],
        "min_impact": 4,
    },
}

BUILT_IN_WATCHLIST_PRESETS = {
    "科技组合": {
        "symbols": [
            "sz300059", "sz002415", "sz002230", "sh688981", "sz300750"
        ],
        "manual_symbols": "",
        "rss_presets": list(RSS_CATALOG),
        "rss_custom": "",
    },
    "银行组合": {
        "symbols": [
            "sz000001", "sh600036", "sh601398", "sh601939", "sh601288"
        ],
        "manual_symbols": "",
        "rss_presets": list(RSS_CATALOG),
        "rss_custom": "",
    },
    "医药组合": {
        "symbols": [
            "sh600276", "sz300760", "sh603259", "sz300015", "sh600436"
        ],
        "manual_symbols": "",
        "rss_presets": list(RSS_CATALOG),
        "rss_custom": "",
    },
}


def _apply_watchlist_preset(preset: dict) -> None:
    st.session_state["watchlist_symbols"] = preset["symbols"]
    st.session_state["watchlist_manual_symbols"] = preset["manual_symbols"]
    st.session_state["watchlist_rss_presets"] = preset["rss_presets"]
    st.session_state["watchlist_rss_urls"] = preset["rss_custom"]


def _apply_filter_preset(preset: dict) -> None:
    st.session_state["news_date_range"] = preset["date_range"]
    st.session_state["news_custom_date_range"] = tuple(
        date.fromisoformat(value) if isinstance(value, str) else value
        for value in preset["custom_dates"]
    )
    st.session_state["news_list_include_failed"] = preset["include_failed"]
    st.session_state["news_list_keyword"] = preset["keyword"]
    st.session_state["news_filter_symbols"] = preset["symbols"]
    st.session_state["news_filter_sources"] = preset["sources"]
    st.session_state["news_filter_sentiments"] = preset["sentiments"]
    st.session_state["news_filter_impact"] = preset["min_impact"]

init_db()
stats = get_stats()
filter_options = get_news_filter_options()
st.session_state.setdefault("news_filter_symbols", filter_options["symbols"])
st.session_state.setdefault("news_filter_sources", filter_options["sources"])
st.session_state.setdefault("news_filter_sentiments", ["positive", "negative", "neutral"])
st.session_state.setdefault("news_filter_impact", 1)
watchlist_preferences = get_watchlist_preferences()
stock_catalog = dict(STOCK_CATALOG)
for symbol in watchlist_preferences["symbols"]:
    stock_catalog.setdefault(symbol, f"{symbol} · 已保存的股票")

default_symbols = [
    symbol
    for symbol in watchlist_preferences["symbols"]
    if symbol in STOCK_CATALOG
]
default_manual_symbols = [
    symbol
    for symbol in watchlist_preferences["symbols"]
    if symbol not in STOCK_CATALOG
]
saved_rss_urls, _ = parse_rss_urls(watchlist_preferences["rss_urls"])
default_rss_presets = [
    url for url in saved_rss_urls if url in RSS_CATALOG
]
default_custom_rss_urls = [
    url
    for url in saved_rss_urls
    if url not in RSS_CATALOG and url not in LEGACY_RSS_PRESETS
]
st.session_state.setdefault("watchlist_symbols", default_symbols)
st.session_state.setdefault(
    "watchlist_manual_symbols",
    "\n".join(default_manual_symbols),
)
st.session_state.setdefault(
    "watchlist_rss_presets",
    default_rss_presets,
)
st.session_state.setdefault(
    "watchlist_rss_urls",
    "\n".join(default_custom_rss_urls),
)
for symbol in default_manual_symbols:
    stock_catalog[symbol] = f"{symbol} · 手动添加"

with st.container(border=True):
    title_left, title_right = st.columns([4, 1], vertical_alignment="center")
    with title_left:
        st.markdown(
            "<div style='letter-spacing:-0.02em;font-size:1.72rem;"
            "font-weight:750;line-height:1.2;'>金融新闻雷达</div>",
            unsafe_allow_html=True,
        )
        st.caption("发现事件 · 核对依据 · 持续跟踪")
    with title_right:
        st.caption("分析仅供信息参考，不构成投资建议")
main_page = st.segmented_control(
    "主导航",
    options=["今日简报", "新闻流", "跟踪复盘", "数据概览"],
    default="今日简报",
    key="main_page",
    width="stretch",
)

with st.sidebar:
    st.header("数据操作")
    with st.expander("关注来源", expanded=True):
        st.markdown("**股票代码**")
        symbols = st.multiselect(
            "关注股票代码",
            options=list(stock_catalog),
            format_func=lambda symbol: stock_catalog[symbol],
            max_selections=10,
            key="watchlist_symbols",
            placeholder="搜索股票代码或名称，最多选择 10 只",
            help="可搜索代码或公司名称；覆盖银行、消费、医药、科技、新能源等行业，最多选择 10 只。",
        )
        st.caption(f"已选择 {len(symbols)} 只股票")
        manual_watchlist_input = st.text_area(
            "其他股票代码",
            height=72,
            placeholder="例如：sz000001、600519、688981.sh",
            help="支持 sh/sz/bj 前缀或纯六位代码；支持空格、逗号或换行分隔。",
            key="watchlist_manual_symbols",
        )
        manual_symbols, invalid_symbols = parse_watchlist(manual_watchlist_input)
        for symbol in manual_symbols:
            stock_catalog.setdefault(symbol, f"{symbol} · 手动添加")
        combined_symbols = list(dict.fromkeys([*symbols, *manual_symbols]))
        if len(combined_symbols) > 10:
            combined_symbols = combined_symbols[:10]
        if invalid_symbols:
            st.caption(f"已忽略 {len(invalid_symbols)} 个无效股票代码")
        elif manual_symbols:
            st.caption(f"手动添加 {len(manual_symbols)} 只股票")

        st.markdown("**RSS 地址**")
        selected_rss_presets = st.multiselect(
            "选择常用 RSS/Atom 来源",
            options=list(RSS_CATALOG),
            format_func=lambda url: RSS_CATALOG[url],
            max_selections=10,
            placeholder="选择一个或多个来源",
            help="预设为大陆媒体 RSS，通常可直连访问；每次最多处理 10 个来源。",
            key="watchlist_rss_presets",
        )
        custom_rss_input = st.text_area(
            "其他 RSS/Atom 地址",
            height=72,
            placeholder="可选：每行一个 HTTP(S) 地址",
            help="填写未列出的公开 RSS/Atom 地址。",
            key="watchlist_rss_urls",
        )
        rss_input = "\n".join([*selected_rss_presets, custom_rss_input])

        saved_watchlist_presets = get_named_presets("watchlist_presets")
        watchlist_presets = {
            **BUILT_IN_WATCHLIST_PRESETS,
            **saved_watchlist_presets,
        }
        with st.container(border=True):
            st.caption("关注组合预设")
            preset_name = st.text_input(
                "预设名称",
                key="watchlist_preset_name",
                placeholder="例如：科技组合",
            )
            preset_names = list(watchlist_presets)
            selected_preset = st.selectbox(
                "选择关注组合",
                options=[""] + preset_names,
                key="watchlist_preset_selected",
                format_func=lambda name: "未选择" if not name else name,
            )
            preset_action_top = st.columns(2)
            if preset_action_top[0].button(
                "保存",
                key="save_watchlist_preset",
                width="stretch",
            ):
                if not preset_name.strip():
                    st.warning("请输入关注组合名称。")
                else:
                    saved_watchlist_presets[preset_name.strip()] = {
                        "symbols": combined_symbols,
                        "manual_symbols": "\n".join(manual_symbols),
                        "rss_presets": selected_rss_presets,
                        "rss_custom": custom_rss_input,
                    }
                    save_named_presets("watchlist_presets", saved_watchlist_presets)
                    st.success("关注组合已保存。")
                    st.rerun()
            preset_action_top[1].button(
                "应用",
                key="apply_watchlist_preset",
                width="stretch",
                disabled=not selected_preset,
                on_click=_apply_watchlist_preset,
                args=(watchlist_presets.get(selected_preset, {}),),
            )
            if st.button(
                "删除",
                key="delete_watchlist_preset",
                width="stretch",
                disabled=not selected_preset or selected_preset not in saved_watchlist_presets,
            ):
                del saved_watchlist_presets[selected_preset]
                save_named_presets("watchlist_presets", saved_watchlist_presets)
                st.success("关注组合预设已删除。")
                st.rerun()

    rss_urls, invalid_rss_urls = parse_rss_urls(rss_input)
    if invalid_rss_urls:
        st.caption(f"已忽略 {len(invalid_rss_urls)} 个无效或超限的 RSS 地址")

    if (
        combined_symbols != watchlist_preferences["symbols"]
        or rss_input != watchlist_preferences["rss_urls"]
    ):
        save_watchlist_preferences(combined_symbols, rss_input)

    fetch_count = st.slider("本次处理上限", 5, 30, 10)
    run_btn = st.button(
        "抓取关注列表并分析",
        type="primary",
        icon=":material/rocket_launch:",
        width="stretch",
        disabled=not combined_symbols and not rss_urls,
        key="fetch_watchlist_news",
    )
    scheduler_config = get_scheduler_config()
    with st.expander("定时抓取与通知", expanded=scheduler_config["enabled"]):
        schedule_enabled = st.toggle(
            "启用定时抓取",
            value=scheduler_config["enabled"],
            key="scheduler_enabled",
        )
        schedule_interval = st.select_slider(
            "抓取间隔",
            options=[15, 30, 60, 120],
            value=scheduler_config["interval_minutes"],
            format_func=lambda minutes: f"{minutes} 分钟",
            key="scheduler_interval",
        )
        schedule_notify = st.toggle(
            "抓取后显示通知",
            value=scheduler_config["notify"],
            key="scheduler_notify",
        )
        if st.button(
            "保存定时设置",
            icon=":material/schedule:",
            width="stretch",
            key="save_scheduler_config",
        ):
            save_scheduler_config(
                schedule_enabled,
                schedule_interval,
                schedule_notify,
            )
            st.success("定时抓取设置已保存。")
            st.rerun()

        scheduled_fetch_due = False
        if schedule_enabled:
            st_autorefresh(
                interval=schedule_interval * 60 * 1000,
                key="scheduled_news_refresh",
            )
            now = datetime.now()
            last_fetch = st.session_state.get("last_scheduled_fetch_at")
            if last_fetch is None:
                st.session_state["last_scheduled_fetch_at"] = now.isoformat(
                    timespec="seconds"
                )
            else:
                try:
                    elapsed = (
                        now - datetime.fromisoformat(last_fetch)
                    ).total_seconds()
                except (TypeError, ValueError):
                    elapsed = schedule_interval * 60
                scheduled_fetch_due = elapsed >= schedule_interval * 60
            if scheduled_fetch_due:
                st.session_state["last_scheduled_fetch_at"] = now.isoformat(
                    timespec="seconds"
                )

    should_fetch = run_btn or (
        schedule_enabled and scheduled_fetch_due
    )
    with st.expander("最近抓取状态", expanded=False):
        fetch_status = st.session_state.get("last_fetch_status")
        if fetch_status:
            st.caption(fetch_status)
        else:
            st.caption("尚未执行抓取或补充分析。")
    with st.expander("历史分析维护", expanded=False):
        st.caption(
            f"待补分析 {stats['needs_analysis']} 条 · "
            f"已有新闻 {stats['total']} 条"
        )
        backfill_btn = st.button(
            f"补充旧新闻分析（{stats['needs_analysis']}）",
            icon=":material/auto_awesome:",
            width="stretch",
            disabled=stats["needs_analysis"] == 0,
            key="backfill_news",
            help="仅处理尚未分析、结构化字段不完整或此前分析失败的记录。",
        )
    with st.expander("数据备份与恢复", expanded=False):
        if st.button(
            "创建数据库备份",
            icon=":material/database:",
            width="stretch",
            key="create_database_backup",
        ):
            backup_path = create_database_backup()
            st.session_state["latest_database_backup"] = str(backup_path)
        latest_backup = st.session_state.get("latest_database_backup")
        if latest_backup:
            from pathlib import Path
            backup_path = Path(latest_backup)
            if backup_path.exists():
                st.download_button(
                    "下载最新备份",
                    data=backup_path.read_bytes(),
                    file_name=backup_path.name,
                    mime="application/octet-stream",
                    icon=":material/download:",
                    width="stretch",
                    key="download_database_backup",
                )
        restore_file = st.file_uploader(
            "恢复数据库备份",
            type=["db"],
            key="restore_database_backup",
            help="恢复前会先进行 SQLite 完整性和表结构检查。",
        )
        if restore_file and st.button(
            "确认恢复",
            icon=":material/history:",
            width="stretch",
            key="confirm_restore_database",
        ):
            try:
                restore_database_backup(restore_file.getvalue())
                init_db()
                st.success("数据库已恢复，并已完成结构检查。")
                st.rerun()
            except (sqlite3.Error, ValueError, OSError) as error:
                st.error(f"恢复失败：{error}")
    st.caption("旧记录没有股票代码时，会使用当前关注列表中的第一只股票作为分析上下文。")

    with st.expander("影响分数标准"):
        for score, description in IMPACT_SCORE_RUBRIC.items():
            st.caption(f"{score}/5：{description}")

    with st.expander("新闻筛选", expanded=main_page == "新闻流"):
        saved_filter_presets = get_named_presets("filter_presets")
        filter_presets = {
            **BUILT_IN_FILTER_PRESETS,
            **saved_filter_presets,
        }
        for preset_name in ("近24小时", "近7天", "较高影响利空"):
            filter_presets[preset_name]["symbols"] = filter_options["symbols"]
            filter_presets[preset_name]["sources"] = filter_options["sources"]
        filter_preset_name = st.text_input(
            "筛选预设名称",
            key="filter_preset_name",
            placeholder="例如：近7天高影响利空",
        )
        filter_preset_names = list(filter_presets)
        selected_filter_preset = st.selectbox(
            "选择筛选预设",
            options=[""] + filter_preset_names,
            key="filter_preset_selected",
            format_func=lambda name: "未选择" if not name else name,
        )
        filter_preset_actions = st.columns(2)
        if filter_preset_actions[0].button(
            "保存筛选",
            key="save_filter_preset",
            width="stretch",
        ):
            if not filter_preset_name.strip():
                st.warning("请输入筛选预设名称。")
            else:
                custom_dates = st.session_state.get(
                    "news_custom_date_range",
                    (date.today() - timedelta(days=6), date.today()),
                )
                saved_filter_presets[filter_preset_name.strip()] = {
                    "date_range": st.session_state.get("news_date_range", "全部时间"),
                    "custom_dates": [
                        value.isoformat() if hasattr(value, "isoformat") else str(value)
                        for value in (custom_dates if isinstance(custom_dates, (list, tuple)) else (custom_dates,))
                    ],
                    "include_failed": st.session_state.get("news_list_include_failed", True),
                    "keyword": st.session_state.get("news_list_keyword", ""),
                    "symbols": st.session_state.get("news_filter_symbols", []),
                    "sources": st.session_state.get("news_filter_sources", []),
                    "sentiments": st.session_state.get("news_filter_sentiments", ["positive", "negative", "neutral"]),
                    "min_impact": st.session_state.get("news_filter_impact", 1),
                }
                save_named_presets("filter_presets", saved_filter_presets)
                st.success("筛选预设已保存。")
                st.rerun()
        filter_preset_actions[1].button(
            "应用筛选",
            key="apply_filter_preset",
            width="stretch",
            disabled=not selected_filter_preset,
            on_click=_apply_filter_preset,
            args=(filter_presets.get(selected_filter_preset, {}),),
        )
        if st.button(
            "删除筛选",
            key="delete_filter_preset",
            width="stretch",
            disabled=(
                not selected_filter_preset
                or selected_filter_preset not in saved_filter_presets
            ),
        ):
            del saved_filter_presets[selected_filter_preset]
            save_named_presets("filter_presets", saved_filter_presets)
            st.success("筛选预设已删除。")
            st.rerun()

        with st.form("news_filters", border=False):
            date_range = st.selectbox(
                "新闻时间",
                ["全部时间", "近24小时", "近7天", "近30天", "自定义"],
                key="news_date_range",
            )
            start_date = end_date = None
            since = None
            if date_range == "近24小时":
                since = (datetime.now() - timedelta(hours=24)).isoformat(
                    timespec="seconds"
                )
            elif date_range == "近7天":
                start_date = (date.today() - timedelta(days=6)).isoformat()
            elif date_range == "近30天":
                start_date = (date.today() - timedelta(days=29)).isoformat()
            elif date_range == "自定义":
                selected_dates = st.date_input(
                    "选择起止日期",
                    value=(date.today() - timedelta(days=6), date.today()),
                    key="news_custom_date_range",
                )
                if isinstance(selected_dates, (list, tuple)):
                    if len(selected_dates) == 1:
                        start_date = end_date = selected_dates[0].isoformat()
                    elif len(selected_dates) == 2:
                        start_date, end_date = (
                            selected_dates[0].isoformat(),
                            selected_dates[1].isoformat(),
                        )
                elif isinstance(selected_dates, date):
                    start_date = end_date = selected_dates.isoformat()

            st.checkbox(
                "显示失败或待分析的新闻",
                key="news_list_include_failed",
            )
            st.text_input(
                "搜索标题或正文",
                placeholder="输入关键词",
                key="news_list_keyword",
                width="stretch",
            )
            selected_symbols = st.multiselect(
                "关注对象",
                options=filter_options["symbols"],
                key="news_filter_symbols",
                help="“未记录”用于查找早期未保存股票代码的新闻。",
            )
            selected_sources = st.multiselect(
                "新闻来源",
                options=filter_options["sources"],
                key="news_filter_sources",
            )
            sentiment_filter = st.multiselect(
                "情绪方向",
                options=["positive", "negative", "neutral"],
                key="news_filter_sentiments",
                format_func=lambda value: {
                    "positive": "利好",
                    "negative": "利空",
                    "neutral": "中性",
                }[value],
            )
            min_impact = st.slider(
                "最低影响分数",
                1,
                5,
                key="news_filter_impact",
            )
            st.form_submit_button(
                "手动应用筛选",
                icon=":material/filter_alt:",
                key="apply_news_filters",
                width="stretch",
            )

if should_fetch:
    with st.spinner("正在抓取关注列表和 RSS 新闻..."):
        unique_news = fetch_watchlist_news(combined_symbols, rss_urls, limit=fetch_count)

    if not unique_news:
        st.session_state["last_fetch_status"] = "最近抓取：未抓到新闻，请检查关注源或网络。"
        st.warning("没有抓到新闻，请检查股票代码、RSS 地址或网络连接。")
    else:
        analyzed_items = [item for item in unique_news if item.get("symbol") != "市场"]
        already_analyzed = get_analyzed_news_keys(unique_news)
        news_to_analyze = [
            item
            for item in unique_news
            if (str(item.get("title") or ""), str(item.get("url") or ""))
            not in already_analyzed
        ]
        if not news_to_analyze:
            st.session_state["last_fetch_status"] = (
                f"最近抓取：抓取 {len(unique_news)} 条，全部已完成分析，无重复调用。"
            )
            st.info("本次抓取的新闻都已分析过，没有重复调用 AI。")
        else:
            analyzed_results = _analyze_batch(
                news_to_analyze,
                combined_symbols[0] if combined_symbols else "市场",
                f"正在分析新闻（跳过已分析 {len(already_analyzed)} 条）...",
            )
            inserted = save_news(analyzed_results)
            failed = sum("error" in item for item in analyzed_results)
            if not scheduled_fetch_due or schedule_notify:
                st.toast(
                    f"抓取 {len(unique_news)} 条（股票新闻 {len(analyzed_items)} 条）；"
                    f"分析 {len(news_to_analyze)} 条，跳过已分析 {len(already_analyzed)} 条；"
                    f"新入库 {inserted} 条，失败 {failed} 条。"
                )
            st.session_state["last_fetch_status"] = (
                f"最近抓取：抓取 {len(unique_news)} 条，分析 {len(news_to_analyze)} 条，"
                f"新入库 {inserted} 条，失败 {failed} 条。"
            )
            st.rerun()

if backfill_btn:
    legacy_news = query_news_needing_analysis(limit=fetch_count)
    if not legacy_news:
        st.session_state["last_fetch_status"] = "最近维护：没有需要补充分析的旧新闻。"
        st.info("没有需要补充分析的旧新闻。")
    else:
        analyzed_results = _analyze_batch(
            legacy_news,
            combined_symbols[0] if combined_symbols else "市场",
            f"正在补充旧新闻分析（共 {len(legacy_news)} 条）...",
        )
        save_news(analyzed_results)
        failed = sum("error" in item for item in analyzed_results)
        st.toast(
            f"已处理 {len(legacy_news)} 条旧新闻；"
            f"本次分析失败 {failed} 条。失败记录可再次重试。"
        )
        st.session_state["last_fetch_status"] = (
            f"最近维护：处理旧新闻 {len(legacy_news)} 条，失败 {failed} 条。"
        )
        st.rerun()

if main_page == "今日简报":
    render_today_brief(stats)
    st.stop()

if main_page == "跟踪复盘":
    st.subheader("跟踪复盘")
    render_tracking_workspace()
    st.stop()

include_failed = st.session_state["news_list_include_failed"]
keyword = st.session_state["news_list_keyword"]

filter_signature = (
    tuple(selected_symbols),
    tuple(selected_sources),
    date_range,
    start_date,
    end_date,
    tuple(sentiment_filter),
    min_impact,
    include_failed,
    keyword.strip(),
)
if st.session_state.get("news_filter_signature") != filter_signature:
    st.session_state["news_filter_signature"] = filter_signature

news_items = query_news(
    min_impact=min_impact,
    limit=None,
    symbols=selected_symbols,
    sources=selected_sources,
    start_date=start_date,
    end_date=end_date,
    since=since,
    search=keyword.strip(),
    sentiments=sentiment_filter,
    analyzed_only=not include_failed,
)

if main_page == "数据概览":
    st.subheader("数据概览")
    st.caption("统计使用当前筛选条件。")
    render_analytics_workspace()
    st.stop()

news_view = st.segmented_control(
    "新闻视图",
    options=["新闻列表", "个股时间线", "同题多源"],
    default="新闻列表",
    key="news_view",
    width="stretch",
)
if news_view == "个股时间线":
    render_news_timeline(news_items)
elif news_view == "同题多源":
    render_multi_source_events(news_items)
else:
    render_news_feed(news_items)

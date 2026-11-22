# src/storage.py
import json
import logging
import math
import sqlite3
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "news_radar.db"
EVENT_TRACKING_STATUSES = {"tracking", "confirmed", "clarified", "expired"}
STRUCTURED_ANALYSIS_FIELDS = (
    "event_type",
    "affected_scope",
    "impact_score",
    "key_facts",
    "impact_path",
    "evidence_quotes",
    "time_horizon",
    "confidence",
    "watch_items",
)


def _analysis_field_complete(field: str) -> str:
    if field == "impact_score":
        return (
            "typeof(impact_score) IN ('integer', 'real') "
            "AND impact_score BETWEEN 1 AND 5 "
            "AND impact_score = CAST(impact_score AS INTEGER)"
        )
    if field == "evidence_quotes":
        return (
            "CASE WHEN evidence_quotes IS NULL OR NOT json_valid(evidence_quotes) "
            "THEN 0 ELSE json_type(evidence_quotes) = 'array' END"
        )
    return f"{field} IS NOT NULL"


def _analysis_field_missing(field: str) -> str:
    if field == "impact_score":
        return (
            "(impact_score IS NULL "
            "OR typeof(impact_score) NOT IN ('integer', 'real') "
            "OR impact_score < 1 OR impact_score > 5 "
            "OR impact_score != CAST(impact_score AS INTEGER))"
        )
    if field == "evidence_quotes":
        return (
            "(CASE WHEN evidence_quotes IS NULL OR NOT json_valid(evidence_quotes) "
            "THEN 1 ELSE json_type(evidence_quotes) != 'array' END)"
        )
    return f"{field} IS NULL"


def _complete_analysis_condition() -> str:
    return " AND ".join(
        _analysis_field_complete(field) for field in STRUCTURED_ANALYSIS_FIELDS
    )


def _incomplete_analysis_condition() -> str:
    return " OR ".join(
        _analysis_field_missing(field) for field in STRUCTURED_ANALYSIS_FIELDS
    )


def _normalize_stored_impact_score(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 1 <= value <= 5
        or value != int(value)
    ):
        return None
    return int(value)


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.create_function("normalize_datetime", 1, _normalize_datetime)
    return conn


def _normalize_datetime(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def init_db():
    """初始化数据库表结构（幂等，可重复调用）"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            symbol TEXT,
            content TEXT,
            source TEXT,
            publish_time TEXT,
            url TEXT,
            sentiment TEXT,
            impact_score INTEGER,
            reason TEXT,
            event_type TEXT,
            affected_scope TEXT,
            key_facts TEXT,
            impact_path TEXT,
            evidence_quotes TEXT,
            time_horizon TEXT,
            confidence INTEGER,
            watch_items TEXT,
            analysis_model TEXT,
            analysis_error TEXT,
            analyzed_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(title, url)
        );
        CREATE INDEX IF NOT EXISTS idx_sentiment ON news(sentiment);
        CREATE INDEX IF NOT EXISTS idx_created ON news(created_at);
        CREATE TABLE IF NOT EXISTS watch_item_tracking (
            news_id INTEGER NOT NULL,
            item_index INTEGER NOT NULL CHECK(item_index >= 0),
            status TEXT NOT NULL CHECK(status IN ('pending', 'verified', 'dismissed')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (news_id, item_index),
            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analysis_feedback (
            news_id INTEGER PRIMARY KEY,
            rating TEXT NOT NULL CHECK(rating IN ('reasonable', 'needs_revision')),
            corrected_score INTEGER
                CHECK(corrected_score IS NULL OR corrected_score BETWEEN 1 AND 5),
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_tracking (
            event_news_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'tracking'
                CHECK(status IN ('tracking', 'confirmed', 'clarified', 'expired')),
            outcome TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (event_news_id) REFERENCES news(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS event_followups (
            event_news_id INTEGER NOT NULL,
            followup_news_id INTEGER NOT NULL,
            linked_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY (event_news_id, followup_news_id),
            CHECK(event_news_id != followup_news_id),
            FOREIGN KEY (event_news_id) REFERENCES news(id) ON DELETE CASCADE,
            FOREIGN KEY (followup_news_id) REFERENCES news(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS event_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_news_id INTEGER NOT NULL,
            status TEXT NOT NULL
                CHECK(status IN ('tracking', 'confirmed', 'clarified', 'expired')),
            outcome TEXT NOT NULL DEFAULT '',
            changed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (event_news_id) REFERENCES news(id) ON DELETE CASCADE
        );
    """)
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(news)").fetchall()
    }
    new_columns = {
        "symbol": "TEXT",
        "event_type": "TEXT",
        "affected_scope": "TEXT",
        "key_facts": "TEXT",
        "impact_path": "TEXT",
        "evidence_quotes": "TEXT",
        "time_horizon": "TEXT",
        "confidence": "INTEGER",
        "watch_items": "TEXT",
        "analysis_model": "TEXT",
        "analysis_error": "TEXT",
    }
    for column, column_type in new_columns.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE news ADD COLUMN {column} {column_type}")
    conn.commit()
    conn.close()
    print(f"数据库初始化完成: {DB_PATH.absolute()}")


def get_watchlist_preferences() -> dict:
    """Load saved watchlist and RSS inputs."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT key, value FROM app_settings
            WHERE key IN ('watchlist_symbols', 'watchlist_rss_urls')"""
        ).fetchall()
    finally:
        conn.close()

    preferences = {
        "symbols": ["sz000001"],
        "rss_urls": "",
    }
    for row in rows:
        value = json.loads(row["value"])
        if row["key"] == "watchlist_symbols":
            if not isinstance(value, list) or not all(
                isinstance(symbol, str) for symbol in value
            ):
                raise ValueError("已保存的关注股票设置格式无效")
            preferences["symbols"] = value
        elif row["key"] == "watchlist_rss_urls":
            if not isinstance(value, str):
                raise ValueError("已保存的 RSS 设置格式无效")
            preferences["rss_urls"] = value
    return preferences


def save_watchlist_preferences(symbols: list[str], rss_urls: str) -> None:
    """Persist watchlist and RSS inputs for the next app session."""
    settings = (
        ("watchlist_symbols", json.dumps(symbols, ensure_ascii=False)),
        ("watchlist_rss_urls", json.dumps(rss_urls, ensure_ascii=False)),
    )
    conn = _get_conn()
    try:
        conn.executemany(
            """INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            settings,
        )
        conn.commit()
    finally:
        conn.close()


def get_named_presets(setting_key: str) -> dict[str, dict]:
    """Return validated named presets stored as an app setting."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (setting_key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    try:
        presets = json.loads(row["value"])
    except json.JSONDecodeError as error:
        raise ValueError("已保存的预设格式无效") from error
    if not isinstance(presets, dict):
        raise ValueError("已保存的预设格式无效")
    if not all(isinstance(name, str) and isinstance(value, dict) for name, value in presets.items()):
        raise ValueError("已保存的预设格式无效")
    return presets


def save_named_presets(setting_key: str, presets: dict[str, dict]) -> None:
    """Persist all named presets for a setting key."""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (setting_key, json.dumps(presets, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_scheduler_config() -> dict:
    """Load the periodic fetching configuration."""
    presets = get_named_presets("scheduler_config")
    config = presets.get("default", {})
    return {
        "enabled": bool(config.get("enabled", False)),
        "interval_minutes": int(config.get("interval_minutes", 30)),
        "notify": bool(config.get("notify", True)),
    }


def save_scheduler_config(enabled: bool, interval_minutes: int, notify: bool) -> None:
    """Persist the periodic fetching configuration."""
    save_named_presets(
        "scheduler_config",
        {
            "default": {
                "enabled": enabled,
                "interval_minutes": interval_minutes,
                "notify": notify,
            }
        },
    )


def get_analyzed_news_keys(news_list: list[dict]) -> set[tuple[str, str]]:
    """Return unique keys for news items with complete structured analyses."""
    if not news_list:
        return set()

    keys = {
        (str(item.get("title") or ""), str(item.get("url") or ""))
        for item in news_list
    }
    key_list = list(keys)
    analyzed_keys = set()
    conn = _get_conn()
    try:
        for offset in range(0, len(key_list), 400):
            batch = key_list[offset : offset + 400]
            conditions = " OR ".join("(title = ? AND url = ?)" for _ in batch)
            parameters = [value for key in batch for value in key]
            rows = conn.execute(
                f"""SELECT title, url FROM news
                WHERE sentiment IS NOT NULL AND analysis_error IS NULL
                    AND {_complete_analysis_condition()}
                    AND ({conditions})""",
                parameters,
            ).fetchall()
            analyzed_keys.update((row["title"], row["url"]) for row in rows)
    finally:
        conn.close()
    return analyzed_keys


def query_news_needing_analysis(limit: int = 20) -> list[dict]:
    """Return failed, pending, or legacy news missing structured analysis fields."""
    conn = _get_conn()
    incomplete_fields = _incomplete_analysis_condition()
    rows = conn.execute(
        f"""SELECT * FROM news
        WHERE analysis_error IS NOT NULL OR sentiment IS NULL OR {incomplete_fields}
        ORDER BY created_at ASC
        LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    news = [dict(row) for row in rows]
    for item in news:
        item["impact_score"] = _normalize_stored_impact_score(
            item.get("impact_score")
        )
        for field in ("key_facts", "watch_items", "evidence_quotes"):
            if field == "evidence_quotes" and item[field] is None:
                continue
            try:
                item[field] = json.loads(item[field]) if item[field] else []
            except (TypeError, json.JSONDecodeError):
                logger.warning(
                    "新闻记录的 %s 字段不是有效 JSON，标题: %s",
                    field,
                    item["title"],
                )
                item[field] = []
    return news


def save_news(news_list: list[dict], force_update: bool = False) -> int:
    """批量保存新闻到数据库，自动去重。

    force_update=True 时，成功分析结果会覆盖已有分析；失败时仍保留已有成功结果。

    Returns:
        实际新写入的条数
    """
    if not news_list:
        return 0

    conn = _get_conn()
    inserted = 0
    incomplete_fields = _incomplete_analysis_condition()
    update_guard = (
        ""
        if force_update
        else f""" AND (analysis_error IS NOT NULL OR sentiment IS NULL
            OR {incomplete_fields})"""
    )

    for item in news_list:
        try:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            cursor = conn.execute(
                """INSERT OR IGNORE INTO news
                (title, symbol, content, source, publish_time, url,
                 sentiment, impact_score, reason, event_type, affected_scope,
                 key_facts, impact_path, evidence_quotes, time_horizon, confidence,
                 watch_items, analysis_model, analysis_error, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    title,
                    item.get("symbol"),
                    item.get("content", ""),
                    item.get("source", ""),
                    item.get("publish_time", ""),
                    url,
                    item.get("sentiment"),
                    item.get("impact_score"),
                    item.get("reason"),
                    item.get("event_type"),
                    item.get("affected_scope"),
                    json.dumps(item.get("key_facts", []), ensure_ascii=False),
                    item.get("impact_path"),
                    json.dumps(item.get("evidence_quotes") or [], ensure_ascii=False),
                    item.get("time_horizon"),
                    item.get("confidence"),
                    json.dumps(item.get("watch_items", []), ensure_ascii=False),
                    item.get("analysis_model"),
                    item.get("error"),
                    item.get("analyzed_at"),
                ),
            )
            if cursor.rowcount == 1:
                inserted += 1
            elif item.get("error"):
                conn.execute(
                    f"""UPDATE news SET analysis_error = ?, analyzed_at = ?
                    WHERE title = ? AND url = ?
                        AND (analysis_error IS NOT NULL OR sentiment IS NULL
                        OR {incomplete_fields})""",
                    (item.get("error"), item.get("analyzed_at"), title, url),
                )
            else:
                conn.execute(
                    f"""UPDATE news SET
                        symbol = COALESCE(symbol, ?),
                        content = ?, source = ?, publish_time = ?, sentiment = ?,
                        impact_score = ?, reason = ?, event_type = ?,
                        affected_scope = ?, key_facts = ?, impact_path = ?,
                        evidence_quotes = ?, time_horizon = ?, confidence = ?,
                        watch_items = ?,
                        analysis_model = ?, analysis_error = ?, analyzed_at = ?
                    WHERE title = ? AND url = ?
                        {update_guard}""",
                    (
                        item.get("symbol"),
                        item.get("content", ""),
                        item.get("source", ""),
                        item.get("publish_time", ""),
                        item.get("sentiment"),
                        item.get("impact_score"),
                        item.get("reason"),
                        item.get("event_type"),
                        item.get("affected_scope"),
                        json.dumps(item.get("key_facts", []), ensure_ascii=False),
                        item.get("impact_path"),
                        json.dumps(
                            item.get("evidence_quotes") or [],
                            ensure_ascii=False,
                        ),
                        item.get("time_horizon"),
                        item.get("confidence"),
                        json.dumps(item.get("watch_items", []), ensure_ascii=False),
                        item.get("analysis_model"),
                        item.get("error"),
                        item.get("analyzed_at"),
                        title,
                        url,
                    ),
                )
        except Exception as e:
            logger.error(f"保存新闻失败: {e}, 标题: {item.get('title', '')[:30]}")

    conn.commit()
    conn.close()
    return inserted


def query_news(
    sentiment: str | None = None,
    min_impact: int = 1,
    limit: int | None = 20,
    symbols: list[str] | None = None,
    sources: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    since: str | None = None,
    search: str | None = None,
    sentiments: list[str] | None = None,
    analyzed_only: bool = False,
    offset: int = 0,
) -> list[dict]:
    """查询新闻，可按情绪和最低影响分筛选。

    Args:
        sentiment: 过滤情绪类型 (positive/negative/neutral)，None 表示不过滤
        min_impact: 最低影响分数 (1-5)
        limit: 最大返回条数；None 表示不限制

    Returns:
        新闻列表，按发布时间倒序排列
    """
    if sentiments is not None and not sentiments:
        return []
    if symbols is not None and not symbols:
        return []
    if sources is not None and not sources:
        return []

    conn = _get_conn()

    query = (
        "SELECT * FROM news WHERE (impact_score >= ? OR "
        f"{_analysis_field_missing('impact_score')})"
    )
    params: list = [min_impact]

    if sentiment:
        query += " AND sentiment = ?"
        params.append(sentiment)

    if sentiments is not None:
        placeholders = ", ".join("?" for _ in sentiments)
        query += f" AND sentiment IN ({placeholders})"
        params.extend(sentiments)

    if symbols is not None:
        include_unassigned = "未记录" in symbols
        selected_symbols = [symbol for symbol in symbols if symbol != "未记录"]
        symbol_conditions = []
        if selected_symbols:
            placeholders = ", ".join("?" for _ in selected_symbols)
            symbol_conditions.append(f"symbol IN ({placeholders})")
            params.extend(selected_symbols)
        if include_unassigned:
            symbol_conditions.append("(symbol IS NULL OR symbol = '')")
        if symbol_conditions:
            query += " AND (" + " OR ".join(symbol_conditions) + ")"

    if sources is not None:
        include_unknown_source = "未知来源" in sources
        selected_sources = [source for source in sources if source != "未知来源"]
        source_conditions = []
        if selected_sources:
            placeholders = ", ".join("?" for _ in selected_sources)
            source_conditions.append(f"source IN ({placeholders})")
            params.extend(selected_sources)
        if include_unknown_source:
            source_conditions.append("(source IS NULL OR source = '')")
        if source_conditions:
            query += " AND (" + " OR ".join(source_conditions) + ")"

    if since:
        query += (
            " AND datetime(normalize_datetime(publish_time)) "
            ">= datetime(normalize_datetime(?))"
        )
        params.append(since)
    if start_date:
        query += " AND date(normalize_datetime(publish_time)) >= date(?)"
        params.append(start_date)
    if end_date:
        query += " AND date(normalize_datetime(publish_time)) <= date(?)"
        params.append(end_date)
    if search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query += " AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"
        search_pattern = f"%{escaped_search}%"
        params.extend((search_pattern, search_pattern))

    if analyzed_only:
        query += " AND sentiment IS NOT NULL AND analysis_error IS NULL"
        query += " AND " + _complete_analysis_condition()

    query += (
        " ORDER BY datetime(normalize_datetime(publish_time)) DESC, "
        "created_at DESC, "
        "COALESCE(impact_score, 0) DESC, id DESC"
    )
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend((limit, offset))

    rows = conn.execute(query, params).fetchall()
    conn.close()
    news = [dict(row) for row in rows]
    for item in news:
        item["impact_score"] = _normalize_stored_impact_score(
            item.get("impact_score")
        )
        for field in ("key_facts", "watch_items", "evidence_quotes"):
            if field == "evidence_quotes" and item[field] is None:
                continue
            try:
                item[field] = json.loads(item[field]) if item[field] else []
            except (TypeError, json.JSONDecodeError):
                logger.warning("新闻记录的 %s 字段不是有效 JSON，标题: %s", field, item["title"])
                item[field] = []
    return news


def query_watch_items(
    status: str | None = "pending",
    limit: int | None = 50,
    offset: int = 0,
    search: str | None = None,
    symbols: list[str] | None = None,
    sources: list[str] | None = None,
) -> list[dict]:
    """Return persisted follow-up items, including their tracking status."""
    allowed_statuses = {"pending", "verified", "dismissed"}
    if status is not None and status not in allowed_statuses:
        raise ValueError("无效的跟踪状态")
    if (limit is not None and limit < 0) or offset < 0:
        raise ValueError("limit 和 offset 必须大于或等于 0")

    conn = _get_conn()
    try:
        query = """SELECT n.id AS news_id, n.symbol, n.title, n.source,
                n.publish_time, n.url, CAST(item.key AS INTEGER) AS item_index,
                item.value AS watch_item,
                COALESCE(tracking.status, 'pending') AS status,
                tracking.updated_at
            FROM news AS n
            JOIN json_each(
                CASE WHEN json_valid(n.watch_items)
                    THEN n.watch_items ELSE '[]' END
            ) AS item
            LEFT JOIN watch_item_tracking AS tracking
                ON tracking.news_id = n.id
                AND tracking.item_index = CAST(item.key AS INTEGER)
            WHERE item.type = 'text' AND trim(item.value) != ''
                AND (? IS NULL OR COALESCE(tracking.status, 'pending') = ?)
            ORDER BY datetime(normalize_datetime(n.publish_time)) DESC,
                n.created_at DESC,
                n.id DESC, CAST(item.key AS INTEGER)"""
        params: list = [status, status]
        if search and search.strip():
            escaped_search = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.replace(
                "\n            ORDER BY",
                "\n                AND (item.value LIKE ? ESCAPE '\\' OR n.title LIKE ? ESCAPE '\\')"
                "\n            ORDER BY",
            )
            pattern = f"%{escaped_search}%"
            params.extend((pattern, pattern))
        if symbols:
            placeholders = ", ".join("?" for _ in symbols)
            query = query.replace(
                "\n            ORDER BY",
                f"\n                AND n.symbol IN ({placeholders})"
                "\n            ORDER BY",
            )
            params.extend(symbols)
        if sources:
            placeholders = ", ".join("?" for _ in sources)
            query = query.replace(
                "\n            ORDER BY",
                f"\n                AND n.source IN ({placeholders})"
                "\n            ORDER BY",
            )
            params.extend(sources)
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend((limit, offset))
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_watch_items_status(
    items: list[tuple[int, int]], status: str
) -> int:
    """Batch-update persisted statuses for follow-up items."""
    allowed_statuses = {"pending", "verified", "dismissed"}
    if status not in allowed_statuses:
        raise ValueError("无效的跟踪状态")
    if not items:
        return 0
    if len(set(items)) != len(items):
        raise ValueError("事项列表不可重复")
    updated = 0
    for news_id, item_index in items:
        set_watch_item_status(news_id, item_index, status)
        updated += 1
    return updated


def set_watch_item_status(news_id: int, item_index: int, status: str) -> None:
    """Persist the review status for one generated follow-up item."""
    allowed_statuses = {"pending", "verified", "dismissed"}
    if status not in allowed_statuses:
        raise ValueError("无效的跟踪状态")
    if item_index < 0:
        raise ValueError("item_index 必须大于或等于 0")

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT watch_items FROM news WHERE id = ?", (news_id,)
        ).fetchone()
        if row is None:
            raise ValueError("找不到对应新闻")
        try:
            items = json.loads(row["watch_items"] or "[]")
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("新闻的后续观察事项格式无效") from error
        if (
            not isinstance(items, list)
            or item_index >= len(items)
            or not isinstance(items[item_index], str)
        ):
            raise ValueError("找不到对应的后续观察事项")

        conn.execute(
            """INSERT INTO watch_item_tracking (news_id, item_index, status)
            VALUES (?, ?, ?)
            ON CONFLICT(news_id, item_index) DO UPDATE SET
                status = excluded.status,
                updated_at = datetime('now', 'localtime')""",
            (news_id, item_index, status),
        )
        conn.commit()
    finally:
        conn.close()


def start_event_tracking(event_news_id: int) -> bool:
    """Start tracking an analyzed news item as an event."""
    if isinstance(event_news_id, bool) or not isinstance(event_news_id, int):
        raise ValueError("event_news_id 必须是正整数")

    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT 1 FROM news
            WHERE id = ? AND sentiment IS NOT NULL AND analysis_error IS NULL""",
            (event_news_id,),
        ).fetchone()
        if row is None:
            raise ValueError("找不到已完成分析的新闻")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO event_tracking (event_news_id) VALUES (?)",
            (event_news_id,),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def query_tracked_events(
    status: str | None = None, limit: int = 50, offset: int = 0
) -> list[dict]:
    """Return tracked event roots and their follow-up counts."""
    if status is not None and status not in EVENT_TRACKING_STATUSES:
        raise ValueError("无效的事件状态")
    if limit < 0 or offset < 0:
        raise ValueError("limit 和 offset 必须大于或等于 0")

    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT tracking.event_news_id, tracking.status, tracking.outcome,
                tracking.created_at AS tracking_created_at,
                tracking.updated_at AS tracking_updated_at,
                news.title, news.symbol, news.source, news.url, news.publish_time,
                news.event_type, news.impact_score,
                COUNT(followups.followup_news_id) AS followup_count
            FROM event_tracking AS tracking
            JOIN news ON news.id = tracking.event_news_id
            LEFT JOIN event_followups AS followups
                ON followups.event_news_id = tracking.event_news_id
            WHERE (? IS NULL OR tracking.status = ?)
            GROUP BY tracking.event_news_id
            ORDER BY tracking.updated_at DESC, tracking.event_news_id DESC
            LIMIT ? OFFSET ?""",
            (status, status, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_event_tracking_status(
    event_news_id: int, status: str, outcome: str = ""
) -> None:
    """Update an event's lifecycle status and human-written outcome."""
    if (
        isinstance(event_news_id, bool)
        or not isinstance(event_news_id, int)
        or event_news_id <= 0
    ):
        raise ValueError("event_news_id 必须是正整数")
    if status not in EVENT_TRACKING_STATUSES:
        raise ValueError("无效的事件状态")
    if not isinstance(outcome, str) or len(outcome) > 500:
        raise ValueError("事件结论必须是 500 字以内的文本")

    conn = _get_conn()
    try:
        previous = conn.execute(
            "SELECT status, outcome FROM event_tracking WHERE event_news_id = ?",
            (event_news_id,),
        ).fetchone()
        if previous is None:
            raise ValueError("该新闻尚未加入事件跟踪")
        normalized_outcome = outcome.strip()
        cursor = conn.execute(
            """UPDATE event_tracking SET status = ?, outcome = ?,
                updated_at = datetime('now', 'localtime')
            WHERE event_news_id = ?""",
            (status, normalized_outcome, event_news_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("该新闻尚未加入事件跟踪")
        if (
            previous["status"] != status
            or previous["outcome"] != normalized_outcome
        ):
            conn.execute(
                """INSERT INTO event_status_history
                    (event_news_id, status, outcome)
                VALUES (?, ?, ?)""",
                (event_news_id, status, normalized_outcome),
            )
        conn.commit()
    finally:
        conn.close()


def query_event_status_history(event_news_id: int) -> list[dict]:
    """Return status and outcome changes for a tracked event."""
    if (
        isinstance(event_news_id, bool)
        or not isinstance(event_news_id, int)
        or event_news_id <= 0
    ):
        raise ValueError("event_news_id 必须是正整数")
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT status, outcome, changed_at
            FROM event_status_history
            WHERE event_news_id = ?
            ORDER BY changed_at DESC, id DESC""",
            (event_news_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_events_tracking_status(
    event_news_ids: list[int], status: str, outcome: str = ""
) -> int:
    """Batch-update lifecycle status for tracked events."""
    if not event_news_ids:
        return 0
    if any(
        isinstance(news_id, bool)
        or not isinstance(news_id, int)
        or news_id <= 0
        for news_id in event_news_ids
    ):
        raise ValueError("event_news_ids 包含无效事件")
    if len(set(event_news_ids)) != len(event_news_ids):
        raise ValueError("event_news_ids 不可重复")
    updated = 0
    for event_news_id in event_news_ids:
        set_event_tracking_status(event_news_id, status, outcome)
        updated += 1
    return updated


def query_event_followup_candidates(
    event_news_id: int, limit: int = 20
) -> list[dict]:
    """Suggest later same-symbol reports for user-confirmed event linking."""
    if isinstance(event_news_id, bool) or not isinstance(event_news_id, int):
        raise ValueError("event_news_id 必须是正整数")
    if limit < 0:
        raise ValueError("limit 必须大于或等于 0")

    conn = _get_conn()
    try:
        event = conn.execute(
            """SELECT news.symbol, news.event_type, news.publish_time,
                news.created_at
            FROM event_tracking
            JOIN news ON news.id = event_tracking.event_news_id
            WHERE event_tracking.event_news_id = ?""",
            (event_news_id,),
        ).fetchone()
        if event is None:
            raise ValueError("找不到已跟踪的事件")
        if not event["symbol"]:
            return []

        event_type_filter = event["event_type"]
        rows = conn.execute(
            """SELECT news.id, news.title, news.symbol, news.source,
                news.url, news.publish_time, news.event_type,
                news.sentiment, news.impact_score
            FROM news
            WHERE news.id != ? AND news.symbol = ?
                AND (? IS NULL OR ? = '' OR ? = '其他'
                    OR news.event_type = ?)
                AND datetime(COALESCE(
                    normalize_datetime(news.publish_time),
                    normalize_datetime(news.created_at)
                )) > datetime(COALESCE(
                    normalize_datetime(?), normalize_datetime(?)
                ))
                AND NOT EXISTS (
                    SELECT 1 FROM event_followups
                    WHERE event_followups.event_news_id = ?
                        AND event_followups.followup_news_id = news.id
                )
            ORDER BY datetime(COALESCE(
                normalize_datetime(news.publish_time),
                normalize_datetime(news.created_at)
            )) DESC, news.id DESC
            LIMIT ?""",
            (
                event_news_id,
                event["symbol"],
                event_type_filter,
                event_type_filter,
                event_type_filter,
                event_type_filter,
                event["publish_time"],
                event["created_at"],
                event_news_id,
                limit,
            ),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def link_event_followup(event_news_id: int, followup_news_id: int) -> None:
    """Link an eligible later article to an event after user confirmation."""
    if (
        isinstance(event_news_id, bool)
        or not isinstance(event_news_id, int)
        or isinstance(followup_news_id, bool)
        or not isinstance(followup_news_id, int)
    ):
        raise ValueError("新闻 ID 必须是正整数")
    if event_news_id == followup_news_id:
        raise ValueError("事件起始新闻不能关联为后续新闻")

    conn = _get_conn()
    try:
        candidate = conn.execute(
            """SELECT 1
            FROM event_tracking AS tracking
            JOIN news AS event ON event.id = tracking.event_news_id
            JOIN news AS followup ON followup.id = ?
            WHERE tracking.event_news_id = ?
                AND event.symbol IS NOT NULL AND event.symbol != ''
                AND followup.symbol = event.symbol
                AND (event.event_type IS NULL OR event.event_type = ''
                    OR event.event_type = '其他'
                    OR followup.event_type = event.event_type)
                AND datetime(COALESCE(
                    normalize_datetime(followup.publish_time),
                    normalize_datetime(followup.created_at)
                )) > datetime(COALESCE(
                    normalize_datetime(event.publish_time),
                    normalize_datetime(event.created_at)
                ))""",
            (followup_news_id, event_news_id),
        ).fetchone()
        if candidate is None:
            raise ValueError("该新闻不符合此事件的后续候选条件")

        conn.execute(
            """INSERT OR IGNORE INTO event_followups
                (event_news_id, followup_news_id)
            VALUES (?, ?)""",
            (event_news_id, followup_news_id),
        )
        conn.commit()
    finally:
        conn.close()


def query_event_followups(event_news_id: int) -> list[dict]:
    """Return articles manually linked to a tracked event."""
    if isinstance(event_news_id, bool) or not isinstance(event_news_id, int):
        raise ValueError("event_news_id 必须是正整数")

    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT news.id, news.title, news.symbol, news.source,
                news.url, news.publish_time, news.event_type,
                news.sentiment, news.impact_score, event_followups.linked_at
            FROM event_followups
            JOIN news ON news.id = event_followups.followup_news_id
            WHERE event_followups.event_news_id = ?
            ORDER BY datetime(COALESCE(
                normalize_datetime(news.publish_time),
                normalize_datetime(news.created_at)
            )) DESC, news.id DESC""",
            (event_news_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def query_analysis_feedback(news_ids: list[int]) -> dict[int, dict]:
    """Return saved human review feedback for the requested news records."""
    if not news_ids:
        return {}
    if any(
        isinstance(news_id, bool) or not isinstance(news_id, int) or news_id <= 0
        for news_id in news_ids
    ):
        raise ValueError("news_ids 必须是正整数")

    feedback = {}
    conn = _get_conn()
    try:
        unique_ids = list(dict.fromkeys(news_ids))
        for offset in range(0, len(unique_ids), 400):
            batch = unique_ids[offset : offset + 400]
            placeholders = ", ".join("?" for _ in batch)
            rows = conn.execute(
                f"""SELECT news_id, rating, corrected_score, comment,
                    created_at, updated_at
                FROM analysis_feedback WHERE news_id IN ({placeholders})""",
                batch,
            ).fetchall()
            feedback.update({row["news_id"]: dict(row) for row in rows})
    finally:
        conn.close()
    return feedback


def save_analysis_feedback(
    news_id: int,
    rating: str,
    corrected_score: int | None = None,
    comment: str = "",
) -> None:
    """Persist a human review without changing the model's analysis."""
    if isinstance(news_id, bool) or not isinstance(news_id, int) or news_id <= 0:
        raise ValueError("news_id 必须是正整数")
    if rating not in {"reasonable", "needs_revision"}:
        raise ValueError("无效的分析反馈")
    if corrected_score is not None and (
        isinstance(corrected_score, bool)
        or not isinstance(corrected_score, int)
        or not 1 <= corrected_score <= 5
    ):
        raise ValueError("建议影响分数必须是 1 到 5 的整数")
    if rating == "reasonable" and corrected_score is not None:
        raise ValueError("认为分析合理时不能填写建议影响分数")
    if not isinstance(comment, str) or len(comment) > 500:
        raise ValueError("反馈说明必须是 500 字以内的文本")

    conn = _get_conn()
    try:
        if conn.execute("SELECT 1 FROM news WHERE id = ?", (news_id,)).fetchone() is None:
            raise ValueError("找不到对应新闻")
        conn.execute(
            """INSERT INTO analysis_feedback
                (news_id, rating, corrected_score, comment)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(news_id) DO UPDATE SET
                rating = excluded.rating,
                corrected_score = excluded.corrected_score,
                comment = excluded.comment,
                updated_at = datetime('now', 'localtime')""",
            (news_id, rating, corrected_score, comment.strip()),
        )
        conn.commit()
    finally:
        conn.close()


def get_event_category_stats(limit: int = 12) -> dict[str, list[dict]]:
    """Summarize event types and affected scopes across stored news."""
    if limit < 0:
        raise ValueError("limit 必须大于或等于 0")

    fields = ("event_type", "affected_scope")
    conn = _get_conn()
    try:
        summaries = {}
        for field in fields:
            rows = conn.execute(
                f"""SELECT COALESCE(NULLIF(TRIM({field}), ''), '未标注') AS category,
                    COUNT(*) AS total,
                    SUM(CASE WHEN sentiment = 'negative' AND impact_score >= 4
                        THEN 1 ELSE 0 END) AS high_impact_negative
                FROM news
                GROUP BY COALESCE(NULLIF(TRIM({field}), ''), '未标注')
                ORDER BY total DESC, category
                LIMIT ?""",
                (limit,),
            ).fetchall()
            summaries[field] = [dict(row) for row in rows]
        return summaries
    finally:
        conn.close()


def get_daily_analytics(days: int = 30) -> list[dict]:
    """Aggregate news, sentiment and impact trends by calendar day."""
    if days not in (7, 30, 90):
        raise ValueError("趋势天数仅支持 7、30 或 90")
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT substr(COALESCE(normalize_datetime(publish_time),
                    normalize_datetime(created_at)), 1, 10) AS date,
                COUNT(*) AS total,
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative,
                SUM(CASE WHEN sentiment = 'neutral' THEN 1 ELSE 0 END) AS neutral,
                SUM(CASE WHEN impact_score >= 4 THEN 1 ELSE 0 END) AS high_impact
            FROM news
            WHERE date(COALESCE(normalize_datetime(publish_time),
                    normalize_datetime(created_at))) >= date('now', '-' || ? || ' days')
            GROUP BY substr(COALESCE(normalize_datetime(publish_time),
                    normalize_datetime(created_at)), 1, 10)
            ORDER BY date DESC""",
            (days,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_source_news_preview(source: str, limit: int = 20) -> list[dict]:
    """Return recent news for one source to support analytics drill-down."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("来源不能为空")
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT id, title, publish_time, source, symbol,
                sentiment, impact_score, event_type, url
            FROM news
            WHERE COALESCE(NULLIF(TRIM(source), ''), '未知来源') = ?
            ORDER BY datetime(COALESCE(normalize_datetime(publish_time),
                    normalize_datetime(created_at))) DESC, id DESC
            LIMIT ?""",
            (source, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_source_health(limit: int = 100) -> list[dict]:
    """Summarize stored-news and analysis coverage by source, not source trust."""
    if limit < 0:
        raise ValueError("limit 必须大于或等于 0")

    complete_fields = _complete_analysis_condition()
    conn = _get_conn()
    try:
        rows = conn.execute(
            f"""SELECT COALESCE(NULLIF(TRIM(source), ''), '未知来源') AS source,
                COUNT(*) AS total,
                SUM(CASE WHEN sentiment IS NOT NULL
                    AND analysis_error IS NULL AND {complete_fields}
                    THEN 1 ELSE 0 END) AS analyzed,
                SUM(CASE WHEN analysis_error IS NOT NULL THEN 1 ELSE 0 END) AS failed,
                MAX(COALESCE(datetime(normalize_datetime(publish_time)),
                    datetime(created_at))) AS latest_news_time
            FROM news
            GROUP BY COALESCE(NULLIF(TRIM(source), ''), '未知来源')
            ORDER BY total DESC, source
            LIMIT ?""",
            (limit,),
        ).fetchall()
        summaries = []
        for row in rows:
            summary = dict(row)
            summary["pending"] = (
                summary["total"] - summary["analyzed"] - summary["failed"]
            )
            summaries.append(summary)
        return summaries
    finally:
        conn.close()


def get_news_filter_options() -> dict[str, list[str]]:
    """Return distinct stock symbols and sources available for dashboard filters."""
    conn = _get_conn()
    try:
        symbols = [
            row["value"]
            for row in conn.execute(
                """SELECT DISTINCT symbol AS value FROM news
                WHERE symbol IS NOT NULL AND symbol != ''
                ORDER BY symbol"""
            ).fetchall()
        ]
        sources = [
            row["value"]
            for row in conn.execute(
                """SELECT DISTINCT source AS value FROM news
                WHERE source IS NOT NULL AND source != ''
                ORDER BY source"""
            ).fetchall()
        ]
    finally:
        conn.close()
    return {
        "symbols": symbols + ["未记录"],
        "sources": sources + ["未知来源"],
    }


def get_stats() -> dict:
    """获取数据库统计信息。"""
    conn = _get_conn()
    incomplete_fields = _incomplete_analysis_condition()
    complete_fields = _complete_analysis_condition()
    try:
        rows = conn.execute(
            f"""SELECT sentiment, COUNT(*) AS total,
                SUM(CASE WHEN sentiment IS NOT NULL
                    AND analysis_error IS NULL AND {complete_fields}
                    THEN 1 ELSE 0 END) AS analyzed,
                SUM(CASE WHEN analysis_error IS NOT NULL THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN analysis_error IS NOT NULL OR sentiment IS NULL
                    OR {incomplete_fields} THEN 1 ELSE 0 END) AS needs_analysis
            FROM news
            GROUP BY sentiment"""
        ).fetchall()
    finally:
        conn.close()

    by_sentiment = {row["sentiment"]: row["total"] for row in rows}
    total = sum(row["total"] for row in rows)
    analyzed = sum(row["analyzed"] or 0 for row in rows)
    failed = sum(row["failed"] or 0 for row in rows)
    needs_analysis = sum(row["needs_analysis"] or 0 for row in rows)
    return {
        "total": total,
        "analyzed": analyzed,
        "failed": failed,
        "pending": total - analyzed - failed,
        "needs_analysis": needs_analysis,
        "by_sentiment": by_sentiment,
    }


def create_database_backup() -> Path:
    """Create a consistent SQLite backup beside the database."""
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"news-radar-{timestamp}.db"
    source = _get_conn()
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def restore_database_backup(uploaded_bytes: bytes) -> None:
    """Validate and restore an uploaded SQLite database backup."""
    if not uploaded_bytes:
        raise ValueError("备份文件为空")
    if len(uploaded_bytes) > 100 * 1024 * 1024:
        raise ValueError("备份文件不能超过 100 MB")
    temporary_path = DB_PATH.parent / "restore-preview.db"
    temporary_path.write_bytes(uploaded_bytes)
    check = sqlite3.connect(str(temporary_path))
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise ValueError("备份文件未通过 SQLite 完整性检查")
        tables = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "news" not in tables:
            raise ValueError("备份文件不是金融新闻雷达数据库")
    finally:
        check.close()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_path = DB_PATH.with_suffix(".db.restore-old")
    if DB_PATH.exists():
        backup_path.write_bytes(DB_PATH.read_bytes())
    try:
        temporary_path.replace(DB_PATH)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    
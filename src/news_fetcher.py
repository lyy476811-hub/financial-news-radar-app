"""Fetch and normalize financial news from AkShare and RSS feeds."""

import hashlib
import re
from collections import deque
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import akshare as ak
import feedparser
import requests
from src.network import bypass_environment_proxies

_SYMBOL_PATTERN = re.compile(
	r"(?:(sz|sh|bj)(\d{6})|(\d{6})\.(sz|sh|bj)|(\d{6}))",
	re.IGNORECASE,
)


def _value(record: dict[str, Any], *keys: str) -> str:
	"""Return the first populated value from a record's possible field names."""
	for key in keys:
		value = record.get(key)
		if value is not None and str(value).lower() != "nan":
			return str(value)
	return ""


def parse_watchlist(value: str) -> tuple[list[str], list[str]]:
	"""Parse exchange-qualified stock symbols and report invalid entries."""
	symbols = []
	invalid = []
	seen = set()
	for token in re.split(r"[\s,，;；]+", value.strip()):
		if not token:
			continue
		match = _SYMBOL_PATTERN.fullmatch(token)
		if not match:
			invalid.append(token)
			continue
		if match.group(1):
			symbol = f"{match.group(1).lower()}{match.group(2)}"
		elif match.group(3):
			symbol = f"{match.group(4).lower()}{match.group(3)}"
		else:
			code = match.group(5)
			if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
				exchange = "sh"
			elif code.startswith(("430", "831", "833", "870", "871", "872", "873", "920")):
				exchange = "bj"
			else:
				exchange = "sz"
			symbol = f"{exchange}{code}"
		if symbol not in seen:
			seen.add(symbol)
			symbols.append(symbol)
	return symbols, invalid


def parse_rss_urls(value: str, max_feeds: int = 10) -> tuple[list[str], list[str]]:
	"""Parse HTTP(S) RSS URLs and report invalid entries."""
	urls = []
	invalid = []
	seen = set()
	for token in re.split(r"[\s,，;；]+", value.strip()):
		if not token:
			continue
		parsed = urlparse(token)
		if parsed.scheme not in ("http", "https") or not parsed.netloc:
			invalid.append(token)
			continue
		if token not in seen:
			seen.add(token)
			urls.append(token)
	if len(urls) > max_feeds:
		invalid.extend(urls[max_feeds:])
		urls = urls[:max_feeds]
	return urls, invalid


def fetch_watchlist_news(
	symbols: list[str], feed_urls: list[str], limit: int
) -> list[dict]:
	"""Fetch watchlist and RSS news, selecting unique results round-robin by source."""
	if limit <= 0:
		return []

	pools = []
	for symbol in symbols:
		news = fetch_akshare_news(symbol)[:limit]
		pools.append([{**item, "symbol": symbol} for item in news])

	if feed_urls:
		rss_news = fetch_rss_news(feed_urls)[:limit]
		pools.append([{**item, "symbol": "市场"} for item in rss_news])

	queues = [deque(pool) for pool in pools if pool]
	selected = []
	seen = set()
	while queues and len(selected) < limit:
		next_round = []
		for queue in queues:
			if not queue:
				continue
			item = queue.popleft()
			fingerprint = _news_fingerprint(item)
			if fingerprint not in seen:
				seen.add(fingerprint)
				selected.append(item)
			if queue:
				next_round.append(queue)
		queues = next_round
	return selected


def _news_fingerprint(news: dict) -> str:
	title = str(news.get("title") or "").strip().casefold()
	url = str(news.get("url") or "").strip().rstrip("/").casefold()
	return hashlib.md5(f"{title}\0{url}".encode("utf-8")).hexdigest()


def fetch_akshare_news(symbol: str) -> list[dict]:
	"""Fetch recent A-share news from AkShare for a stock symbol."""
	try:
		stock_code = symbol.strip().lower()
		for prefix in ("sz", "sh", "bj"):
			if stock_code.startswith(prefix):
				stock_code = stock_code[len(prefix):]
				break
		for suffix in (".sz", ".sh", ".bj"):
			if stock_code.endswith(suffix):
				stock_code = stock_code[:-len(suffix)]
				break

		akshare_function = ak.stock_news_em
		akshare_requests = akshare_function.__globals__.get("requests", requests)

		def get_with_timeout(*args: Any, **kwargs: Any) -> Any:
			kwargs.setdefault("timeout", 10)
			return akshare_requests.get(*args, **kwargs)

		request_proxy = SimpleNamespace(get=get_with_timeout)
		akshare_globals = akshare_function.__globals__
		original_requests = akshare_globals.get("requests")
		akshare_globals["requests"] = request_proxy
		try:
			with bypass_environment_proxies():
				frame = akshare_function(symbol=stock_code)
		finally:
			if original_requests is not None:
				akshare_globals["requests"] = original_requests

		news_list = []
		for record in frame.to_dict(orient="records"):
			news_list.append(
				{
					"title": _value(record, "新闻标题", "title", "标题"),
					"content": _value(record, "新闻内容", "content", "summary"),
					"source": _value(record, "文章来源", "source", "mediaName"),
					"publish_time": _value(
						record, "发布时间", "publish_time", "date", "published"
					),
					"url": _value(record, "新闻链接", "url", "link"),
				}
			)
		return news_list
	except Exception as error:
		print(f"获取 AkShare 新闻失败 ({symbol}): {error}")
		return []


def fetch_rss_news(feed_urls: list[str]) -> list[dict]:
	"""Fetch and normalize news entries from multiple RSS feed URLs."""
	news_list = []
	for feed_url in feed_urls:
		try:
			with bypass_environment_proxies():
				session = requests.Session()
				session.trust_env = False
				session.headers.update({
					"User-Agent": "Mozilla/5.0 FinancialNewsRadar/1.0",
				})
				response = session.get(feed_url, timeout=10)
				response.raise_for_status()
				parsed_feed = feedparser.parse(response.content)
			feed_source = parsed_feed.feed.get("title", "")
			for entry in parsed_feed.entries:
				content_items = entry.get("content", [])
				content = entry.get("summary", "")
				if not content and content_items:
					content = content_items[0].get("value", "")
				source = entry.get("source", {}).get("title", "") or feed_source
				news_list.append(
					{
						"title": entry.get("title", "") or "",
						"content": content or "",
						"source": source or "",
						"publish_time": entry.get("published", "")
						or entry.get("updated", "")
						or "",
						"url": entry.get("link", "") or "",
					}
				)
		except Exception as error:
			print(f"获取 RSS 新闻失败 ({feed_url}): {error}")
	return news_list


def deduplicate(news_list: list[dict]) -> list[dict]:
	"""Remove duplicate news by the MD5 hash of title and URL."""
	unique_news = []
	seen_hashes = set()
	for news in news_list:
		fingerprint = _news_fingerprint(news)
		if fingerprint not in seen_hashes:
			seen_hashes.add(fingerprint)
			unique_news.append(news)
	return unique_news

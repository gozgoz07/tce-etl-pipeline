"""Collector for RSS feeds specified in config/sources.yaml."""

import calendar
import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import feedparser
import httpx
import yaml

from tce.collectors.base import RawItem
from tce.settings import settings

logger = logging.getLogger(__name__)


def clean_html_summary(raw_html: Optional[str], max_chars: int = 1000) -> Optional[str]:
    """Strip HTML tags, unescape entities, normalize whitespace, and truncate to max_chars."""
    if not raw_html or not raw_html.strip():
        return None

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", raw_html)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize multiple whitespaces and newlines
    normalized = " ".join(text.split())
    if not normalized:
        return None

    return normalized[:max_chars]


def parse_rss_feed_content(content: str, default_lang: str = "en") -> list[RawItem]:
    """Parse RSS/Atom feed content string into a list of RawItems."""
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        err_msg = getattr(parsed, "bozo_exception", "Unknown")
        logger.warning("Unreadable or malformed RSS feed: %s", err_msg)
        return []

    # Determine feed language
    feed_lang = parsed.feed.get("language")
    if feed_lang:
        # Extract 2-letter code if format like en-US
        lang = feed_lang.split("-")[0].split("_")[0].lower()
    else:
        lang = default_lang

    items: list[RawItem] = []
    for entry in parsed.entries:
        item_id = str(entry.get("id") or entry.get("link") or "").strip()
        url = str(entry.get("link") or entry.get("id") or "").strip()
        if not item_id or not url:
            continue

        raw_title = entry.get("title") or ""
        title = " ".join(raw_title.split())
        if not title:
            continue

        # Extract summary or description or content
        raw_summary = entry.get("summary") or entry.get("description")
        if not raw_summary and entry.get("content"):
            content_list = entry.get("content")
            if isinstance(content_list, list) and len(content_list) > 0:
                raw_summary = content_list[0].get("value")

        summary = clean_html_summary(raw_summary, max_chars=1000)

        # Parse publication date
        pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if pub_parsed:
            published_at = datetime.fromtimestamp(
                calendar.timegm(pub_parsed),
                tz=timezone.utc,
            )
        else:
            published_at = datetime.now(timezone.utc)

        items.append(
            RawItem(
                source="rss",
                source_item_id=item_id,
                url=url,
                title=title,
                summary=summary,
                lang=lang,
                published_at=published_at,
                points=0,
                comments=0,
            )
        )

    return items


def load_rss_sources(config_path: Optional[Path] = None) -> list[dict]:
    """Load RSS source definitions from config/sources.yaml."""
    path = config_path or (settings.CONFIG_DIR / "sources.yaml")
    if not path.exists():
        logger.warning("sources.yaml not found at %s", path)
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return []

    return data.get("rss", [])


def fetch_rss_feed(
    url: str,
    client: Optional[httpx.Client] = None,
) -> list[RawItem]:
    """Fetch and parse a single RSS feed with retry logic."""
    owns_client = client is None
    http_client = client or httpx.Client(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
    )

    try:
        response = None
        for attempt in range(settings.HTTP_MAX_RETRIES):
            try:
                response = http_client.get(url)
                response.raise_for_status()
                break
            except Exception as e:
                logger.warning("RSS request attempt %d failed for %s: %s", attempt + 1, url, e)
                if attempt == settings.HTTP_MAX_RETRIES - 1:
                    logger.error("Failed to read RSS feed at %s after retries.", url)
                    return []
                import time

                time.sleep(1.0 * (attempt + 1))

        if response is None:
            return []

        return parse_rss_feed_content(response.text)
    finally:
        if owns_client:
            http_client.close()


def fetch_all_rss_feeds(
    sources: Optional[Sequence[dict]] = None,
    client: Optional[httpx.Client] = None,
) -> list[RawItem]:
    """Fetch all RSS feeds configured in sources."""
    feed_sources = sources if sources is not None else load_rss_sources()
    all_items: list[RawItem] = []

    owns_client = client is None
    http_client = client or httpx.Client(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
    )

    try:
        for src in feed_sources:
            feed_url = src.get("url")
            feed_name = src.get("name", feed_url)
            if not feed_url:
                continue

            logger.info("Collecting RSS feed: %s (%s)", feed_name, feed_url)
            try:
                items = fetch_rss_feed(feed_url, client=http_client)
                all_items.extend(items)
            except Exception as e:
                logger.warning("Skipping unreadable RSS feed %s: %s", feed_name, e)
    finally:
        if owns_client:
            http_client.close()

    logger.info("Collected %d items across %d RSS feeds.", len(all_items), len(feed_sources))
    return all_items

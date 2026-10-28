"""Collector for Hacker News via Algolia API."""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Sequence

import httpx

from tce.collectors.base import RawItem
from tce.settings import settings

logger = logging.getLogger(__name__)


def build_filter_predicate(
    entity_aliases: Optional[Sequence[str]] = None,
    topic_keywords: Optional[Sequence[str]] = None,
) -> Callable[[str], bool]:
    """Build a filtering predicate to check if text contains an entity alias or topic keyword.

    Short aliases (<= 3 chars) are matched case-sensitively.
    Long aliases (> 3 chars) and topic keywords are matched case-insensitively with word boundaries.
    """
    short_aliases: list[str] = []
    case_insensitive_terms: list[str] = []

    for alias in entity_aliases or []:
        a = alias.strip()
        if not a:
            continue
        if len(a) <= 3:
            short_aliases.append(a)
        else:
            case_insensitive_terms.append(a)

    for kw in topic_keywords or []:
        k = kw.strip()
        if k:
            case_insensitive_terms.append(k)

    regex_short: Optional[re.Pattern] = None
    if short_aliases:
        short_aliases.sort(key=len, reverse=True)
        regex_short = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(a) for a in short_aliases) + r")(?!\w)"
        )

    regex_ci: Optional[re.Pattern] = None
    if case_insensitive_terms:
        case_insensitive_terms.sort(key=len, reverse=True)
        regex_ci = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(t) for t in case_insensitive_terms) + r")(?!\w)",
            re.IGNORECASE,
        )

    def predicate(text: str) -> bool:
        if not text:
            return False
        if regex_short and regex_short.search(text):
            return True
        if regex_ci and regex_ci.search(text):
            return True
        return False

    return predicate


def parse_hn_hit(
    hit: dict,
    filter_fn: Optional[Callable[[str], bool]] = None,
) -> Optional[RawItem]:
    """Parse a single Algolia hit into a RawItem if it matches filtering predicate."""
    object_id = str(hit.get("objectID") or "").strip()
    if not object_id:
        return None

    raw_title = hit.get("title") or ""
    title = " ".join(raw_title.split())
    if not title:
        return None

    story_text = hit.get("story_text")
    summary = " ".join(story_text.split()) if story_text else None

    # Filter check on title + story_text
    searchable_text = f"{title} {summary or ''}".strip()
    if filter_fn is not None and not filter_fn(searchable_text):
        return None

    # URL fallback: if url is missing, link to discussion
    url = hit.get("url")
    if not url or not url.strip():
        url = f"https://news.ycombinator.com/item?id={object_id}"

    # Timestamp
    created_at_i = hit.get("created_at_i")
    if created_at_i:
        published_at = datetime.fromtimestamp(int(created_at_i), tz=timezone.utc)
    else:
        published_at = datetime.now(timezone.utc)

    points = int(hit.get("points") or 0)
    comments = int(hit.get("num_comments") or 0)

    return RawItem(
        source="hn",
        source_item_id=object_id,
        url=url,
        title=title,
        summary=summary,
        lang="en",
        published_at=published_at,
        points=points,
        comments=comments,
    )


def parse_hn_response(
    data: dict,
    filter_fn: Optional[Callable[[str], bool]] = None,
) -> list[RawItem]:
    """Parse Algolia search response into RawItems."""
    hits = data.get("hits", [])
    items: list[RawItem] = []
    for hit in hits:
        item = parse_hn_hit(hit, filter_fn=filter_fn)
        if item:
            items.append(item)
    return items


def fetch_hackernews(
    cutoff_hours: int = 48,
    max_pages: int = 5,
    hits_per_page: int = 100,
    filter_fn: Optional[Callable[[str], bool]] = None,
    client: Optional[httpx.Client] = None,
) -> list[RawItem]:
    """Fetch Hacker News stories from Algolia API for the last N hours."""
    base_url = "https://hn.algolia.com/api/v1/search_by_date"
    since_timestamp = int((datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)).timestamp())
    all_items: list[RawItem] = []

    owns_client = client is None
    http_client = client or httpx.Client(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )

    try:
        for page in range(max_pages):
            params = {
                "tags": "story",
                "numericFilters": f"created_at_i>{since_timestamp}",
                "hitsPerPage": hits_per_page,
                "page": page,
            }
            logger.info("Fetching Hacker News page %d...", page + 1)

            response = None
            for attempt in range(settings.HTTP_MAX_RETRIES):
                try:
                    response = http_client.get(base_url, params=params)
                    response.raise_for_status()
                    break
                except Exception as e:
                    logger.warning("Hacker News request attempt %d failed: %s", attempt + 1, e)
                    if attempt == settings.HTTP_MAX_RETRIES - 1:
                        raise
                    time.sleep(2.0 * (attempt + 1))

            if response is None:
                break

            data = response.json()
            hits = data.get("hits", [])
            if not hits:
                logger.info("No more hits on Hacker News page %d. Stopping.", page + 1)
                break

            page_items = parse_hn_response(data, filter_fn=filter_fn)
            all_items.extend(page_items)

            # Check total pages available from Algolia
            nb_pages = data.get("nbPages", 1)
            if page + 1 >= nb_pages:
                break

            # Respect rate limit: 1 request per second
            if page < max_pages - 1:
                time.sleep(1.0)

    finally:
        if owns_client:
            http_client.close()

    logger.info("Fetched %d relevant Hacker News items.", len(all_items))
    return all_items

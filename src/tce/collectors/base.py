"""Base data structures and shared functions for all collectors."""

import hashlib
import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

import psycopg

logger = logging.getLogger(__name__)

ARXIV_ID_PATTERN = re.compile(
    r"(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)?([a-zA-Z\-\.]+/\d+|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?(?:/)?$",
    re.IGNORECASE,
)


@dataclass
class RawItem:
    """Raw item collected from an external source."""

    source: str
    source_item_id: str
    url: str
    title: str
    summary: Optional[str]
    lang: Optional[str]
    published_at: datetime
    points: int = 0
    comments: int = 0

    def __post_init__(self) -> None:
        """Ensure published_at is UTC timezone-aware."""
        if self.published_at.tzinfo is None:
            self.published_at = self.published_at.replace(tzinfo=timezone.utc)
        else:
            self.published_at = self.published_at.astimezone(timezone.utc)


def normalize_url(url: str) -> str:
    """Normalize a URL according to TCE V0 specification.

    - Convert scheme and domain to lowercase.
    - Remove fragment.
    - Remove utm_* query parameters.
    - Remove trailing slash.
    - For arXiv URLs: format as https://arxiv.org/abs/<id_without_version>.
    """
    cleaned_url = url.strip()
    if not cleaned_url:
        return ""

    parsed = urllib.parse.urlparse(cleaned_url)
    netloc_lower = parsed.netloc.lower()

    # Special handling for arXiv
    if "arxiv.org" in netloc_lower:
        match = ARXIV_ID_PATTERN.search(cleaned_url)
        if match:
            clean_id = match.group(1)
            return f"https://arxiv.org/abs/{clean_id}"

    # General normalization
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = netloc_lower

    # Filter out utm_* query params
    filtered_params = []
    if parsed.query:
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            if not k.lower().startswith("utm_"):
                filtered_params.append((k, v))

    new_query = urllib.parse.urlencode(filtered_params) if filtered_params else ""

    # Strip trailing slash from path
    path = parsed.path.rstrip("/")

    return urllib.parse.urlunparse((scheme, netloc, path, "", new_query, ""))


def compute_url_hash(url: str) -> str:
    """Compute SHA-256 hex digest for a normalized URL."""
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def store_raw_items(
    items: Sequence[RawItem],
    conn: psycopg.Connection,
    enrich_fn: Optional[Callable[[RawItem], tuple[list[str], list[int]]]] = None,
) -> tuple[int, int, int]:
    """Store raw items in items table with idempotent upserts.

    Returns:
        tuple (seen_count, new_count, updated_count)
    """
    seen_count = len(items)
    new_count = 0
    updated_count = 0

    with conn.cursor() as cur:
        for item in items:
            norm_url = normalize_url(item.url)
            u_hash = hashlib.sha256(norm_url.encode("utf-8")).hexdigest()

            # Check if item exists by (source, source_item_id) or url_hash
            cur.execute(
                """
                SELECT item_id, source, source_item_id, url_hash
                FROM items
                WHERE (source = %s AND source_item_id = %s) OR url_hash = %s
                LIMIT 1
                """,
                (item.source, item.source_item_id, u_hash),
            )
            existing = cur.fetchone()

            if existing:
                item_id, ex_source, ex_source_id, ex_url_hash = existing
                # If exact same source item, update points and comments
                if ex_source == item.source and ex_source_id == item.source_item_id:
                    cur.execute(
                        """
                        UPDATE items
                        SET points = %s, comments = %s, fetched_at = now()
                        WHERE item_id = %s
                        """,
                        (item.points, item.comments, item_id),
                    )
                    updated_count += 1
                else:
                    # Duplicate on url_hash from another source: ignore (do nothing)
                    logger.debug(
                        "Ignoring duplicate url_hash from different source: %s vs %s",
                        item.source,
                        ex_source,
                    )
            else:
                # Brand new item: enrich and insert
                keywords, entity_ids = (
                    enrich_fn(item) if enrich_fn else ([], [])
                )
                cur.execute(
                    """
                    INSERT INTO items (
                        source, source_item_id, url, url_hash, title, summary,
                        lang, published_at, fetched_at, points, comments,
                        keywords, entity_ids
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s
                    )
                    ON CONFLICT (source, source_item_id) DO UPDATE SET
                        points = EXCLUDED.points,
                        comments = EXCLUDED.comments,
                        fetched_at = now()
                    """,
                    (
                        item.source,
                        item.source_item_id,
                        norm_url,
                        u_hash,
                        item.title,
                        item.summary,
                        item.lang,
                        item.published_at,
                        item.points,
                        item.comments,
                        keywords,
                        entity_ids,
                    ),
                )
                new_count += 1

    logger.info(
        "Items storage summary: %d seen, %d new, %d updated",
        seen_count,
        new_count,
        updated_count,
    )
    return seen_count, new_count, updated_count

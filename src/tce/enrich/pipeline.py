"""Pipeline coordinating entity and keyword enrichment."""

import logging
from typing import Optional

import psycopg

from tce.enrich.entities import EntityMatcher
from tce.enrich.keywords import extract_keywords

logger = logging.getLogger(__name__)


def enrich_text(
    title: str,
    summary: Optional[str],
    lang: Optional[str],
    matcher: EntityMatcher,
) -> tuple[list[str], list[int]]:
    """Enrich text with entity IDs and keywords.

    Returns:
        (keywords, entity_ids)
    """
    text = f"{title} {summary or ''}".strip()
    entity_ids, matched_aliases = matcher.extract(text)
    keywords = extract_keywords(
        text=text,
        lang=lang,
        entity_aliases=matched_aliases,
        max_keywords=8,
    )
    return keywords, entity_ids


def re_enrich_items(conn: psycopg.Connection, since_days: int = 7) -> int:
    """Recalculate keywords and entity_ids for items within the last N days."""
    matcher = EntityMatcher.from_db(conn)
    updated_count = 0

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT item_id, title, summary, lang
            FROM items
            WHERE published_at >= now() - (%s * interval '1 day')
            """,
            (since_days,),
        )
        rows = cur.fetchall()

        for item_id, title, summary, lang in rows:
            keywords, entity_ids = enrich_text(
                title=title,
                summary=summary,
                lang=lang,
                matcher=matcher,
            )
            cur.execute(
                """
                UPDATE items
                SET keywords = %s, entity_ids = %s
                WHERE item_id = %s
                """,
                (keywords, entity_ids, item_id),
            )
            updated_count += 1

    logger.info("Re-enriched %d items published within last %d days.", updated_count, since_days)
    return updated_count

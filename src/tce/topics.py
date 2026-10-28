"""Topic attachment logic based on entity hits and keyword matching."""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Sequence

import psycopg

from tce.settings import settings

logger = logging.getLogger(__name__)


def compute_match_score(
    item_entity_ids: Sequence[int],
    searchable_text: str,
    topic_entity_ids: Sequence[int],
    topic_keywords: Sequence[str],
) -> float:
    """Compute topic match score according to TCE V0 specification.

    - entity_hits = number of topic's entity_ids present in item's entity_ids.
    - keyword_hits = number of topic keywords found in item's title + summary (case-insensitive).
    - match_score = min(1.0, 0.5 * entity_hits + 0.25 * keyword_hits).
    """
    # Entity hits
    item_entities_set = set(item_entity_ids or [])
    topic_entities_set = set(topic_entity_ids or [])
    entity_hits = len(item_entities_set.intersection(topic_entities_set))

    # Keyword hits (case-insensitive with word boundaries)
    keyword_hits = 0
    clean_text = searchable_text.lower()
    for kw in topic_keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        pattern = rf"(?<!\w){re.escape(kw_clean)}(?!\w)"
        if re.search(pattern, clean_text):
            keyword_hits += 1

    raw_score = 0.5 * entity_hits + 0.25 * keyword_hits
    return min(1.0, raw_score)


def attach_items_to_topics(
    conn: psycopg.Connection,
    since_days: int = 7,
    threshold: float = settings.MATCH_SCORE_THRESHOLD,
) -> int:
    """Attach items published in the last N days to matching topics.

    Only pairs with match_score >= threshold (default 0.5) are written to item_topics.
    Returns the number of attachments written/updated.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=since_days)

    with conn.cursor() as cur:
        # Load all topics
        cur.execute("SELECT topic_id, name, keywords, entity_ids FROM topics")
        topics = cur.fetchall()

        if not topics:
            logger.warning("No topics found in database. Seed topics first.")
            return 0

        # Load items published within since_days
        cur.execute(
            """
            SELECT item_id, title, summary, entity_ids
            FROM items
            WHERE published_at >= %s
            """,
            (since_dt,),
        )
        items = cur.fetchall()

        attached_count = 0
        for item_id, title, summary, entity_ids in items:
            searchable_text = f"{title} {summary or ''}"
            for topic_id, _name, keywords, t_entity_ids in topics:
                score = compute_match_score(
                    item_entity_ids=entity_ids or [],
                    searchable_text=searchable_text,
                    topic_entity_ids=t_entity_ids or [],
                    topic_keywords=keywords or [],
                )
                if score >= threshold:
                    cur.execute(
                        """
                        INSERT INTO item_topics (item_id, topic_id, match_score)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (item_id, topic_id) DO UPDATE SET
                            match_score = EXCLUDED.match_score
                        """,
                        (item_id, topic_id, score),
                    )
                    attached_count += 1

    logger.info(
        "Attached %d item-topic pairs (since_days=%d, threshold=%.2f)",
        attached_count,
        since_days,
        threshold,
    )
    return attached_count

"""Coordination service for fetching, enriching, and storing items from all sources."""

import logging

import psycopg

from tce.collectors.arxiv import fetch_arxiv
from tce.collectors.base import RawItem, store_raw_items
from tce.collectors.hackernews import build_filter_predicate, fetch_hackernews
from tce.collectors.huggingface import fetch_hf_models
from tce.collectors.rss import fetch_all_rss_feeds
from tce.enrich.entities import EntityMatcher
from tce.enrich.pipeline import enrich_text

logger = logging.getLogger(__name__)


def collect_and_store(
    conn: psycopg.Connection,
    source: str = "all",
) -> tuple[int, int, int, bool]:
    """Collect from specified source ('hn', 'arxiv', 'rss', 'hf', or 'all'), enrich and store in DB.

    Returns:
        tuple (total_seen, total_new, total_updated, had_errors)
    """
    clean_source = source.strip().lower()
    valid_sources = {"hn", "arxiv", "rss", "hf", "all"}
    if clean_source not in valid_sources:
        raise ValueError(f"Invalid source: '{source}'. Must be one of {valid_sources}")

    # Load entity matcher from DB
    matcher = EntityMatcher.from_db(conn)

    # Load topic keywords for HN filtering
    with conn.cursor() as cur:
        cur.execute("SELECT unnest(keywords) FROM topics")
        topic_keywords = [row[0] for row in cur.fetchall()]

        # Also get all entity aliases
        cur.execute("SELECT unnest(aliases) FROM entities")
        all_aliases = [row[0] for row in cur.fetchall()]

    hn_filter = build_filter_predicate(
        entity_aliases=all_aliases,
        topic_keywords=topic_keywords,
    )

    items_to_store: list[RawItem] = []
    had_errors = False

    # 1. Hacker News
    if clean_source in ("hn", "all"):
        try:
            logger.info("Starting Hacker News collection...")
            hn_items = fetch_hackernews(filter_fn=hn_filter)
            items_to_store.extend(hn_items)
            logger.info("Collected %d HN items passing relevance filter.", len(hn_items))
        except Exception as e:
            logger.error("Hacker News collection failed: %s", e)
            had_errors = True

    # 2. arXiv
    if clean_source in ("arxiv", "all"):
        try:
            logger.info("Starting arXiv collection...")
            arxiv_items = fetch_arxiv()
            items_to_store.extend(arxiv_items)
            logger.info("Collected %d arXiv items.", len(arxiv_items))
        except Exception as e:
            logger.error("arXiv collection failed: %s", e)
            had_errors = True

    # 3. RSS
    if clean_source in ("rss", "all"):
        try:
            logger.info("Starting RSS collection...")
            rss_items = fetch_all_rss_feeds()
            items_to_store.extend(rss_items)
            logger.info("Collected %d RSS items.", len(rss_items))
        except Exception as e:
            logger.error("RSS collection failed: %s", e)
            had_errors = True

    # 4. Hugging Face
    if clean_source in ("hf", "all"):
        try:
            logger.info("Starting Hugging Face models collection...")
            hf_items = fetch_hf_models()
            items_to_store.extend(hf_items)
            logger.info("Collected %d Hugging Face model items.", len(hf_items))
        except Exception as e:
            logger.error("Hugging Face collection failed: %s", e)
            had_errors = True

    # Common enrichment function
    def enrich_fn(raw_item: RawItem) -> tuple[list[str], list[int]]:
        return enrich_text(
            title=raw_item.title,
            summary=raw_item.summary,
            lang=raw_item.lang,
            matcher=matcher,
        )

    # Store in database
    seen, new_count, updated = store_raw_items(
        items=items_to_store,
        conn=conn,
        enrich_fn=enrich_fn,
    )

    return seen, new_count, updated, had_errors

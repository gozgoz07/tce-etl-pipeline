"""Collector for arXiv API."""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from tce.collectors.base import RawItem
from tce.settings import settings

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_ID_REGEX = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?([a-zA-Z\-\.]+/\d+|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


def extract_arxiv_id_from_raw_id(raw_id: str) -> str:
    """Extract arXiv identifier without version from an ID string or URL."""
    match = ARXIV_ID_REGEX.search(raw_id.strip())
    if match:
        return match.group(1)
    # Fallback to cleaning version suffix directly
    cleaned = raw_id.strip().rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", cleaned)


def parse_arxiv_entry(entry: ET.Element) -> Optional[RawItem]:
    """Parse a single Atom XML <entry> into a RawItem."""
    id_elem = entry.find("atom:id", ATOM_NS)
    title_elem = entry.find("atom:title", ATOM_NS)
    summary_elem = entry.find("atom:summary", ATOM_NS)
    pub_elem = entry.find("atom:published", ATOM_NS)

    if id_elem is None or not id_elem.text:
        return None

    raw_id = id_elem.text.strip()
    clean_id = extract_arxiv_id_from_raw_id(raw_id)
    url = f"https://arxiv.org/abs/{clean_id}"

    raw_title = title_elem.text if (title_elem is not None and title_elem.text) else ""
    title = " ".join(raw_title.split())

    raw_summary = (
        summary_elem.text if (summary_elem is not None and summary_elem.text) else ""
    )
    summary = " ".join(raw_summary.split())

    pub_text = pub_elem.text.strip() if (pub_elem is not None and pub_elem.text) else ""
    if pub_text:
        published_at = datetime.fromisoformat(
            pub_text.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    else:
        published_at = datetime.now(timezone.utc)

    return RawItem(
        source="arxiv",
        source_item_id=clean_id,
        url=url,
        title=title,
        summary=summary,
        lang="en",
        published_at=published_at,
        points=0,
        comments=0,
    )


def parse_arxiv_feed(xml_text: str) -> list[RawItem]:
    """Parse entire Atom XML feed string into a list of RawItems."""
    if not xml_text or not xml_text.strip():
        return []

    root = ET.fromstring(xml_text)
    items: list[RawItem] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        item = parse_arxiv_entry(entry)
        if item:
            items.append(item)
    return items


def fetch_arxiv(
    search_query: str = "cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.CV",
    cutoff_hours: int = 48,
    max_pages: int = 5,
    max_results_per_page: int = 100,
    client: Optional[httpx.Client] = None,
) -> list[RawItem]:
    """Fetch arXiv items with pagination and rate-limiting (1 request every 3 seconds)."""
    base_url = "https://export.arxiv.org/api/query"
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    all_items: list[RawItem] = []

    owns_client = client is None
    http_client = client or httpx.Client(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )

    try:
        # Best-effort retrieval of Hugging Face Daily Papers engagement metrics
        hf_metrics: dict[str, tuple[int, int]] = {}
        try:
            from tce.collectors.huggingface import fetch_hf_daily_papers_metrics

            hf_metrics = fetch_hf_daily_papers_metrics(client=http_client)
        except Exception as e:
            logger.warning("Could not fetch Hugging Face metrics for arXiv: %s", e)

        for page in range(max_pages):
            start = page * max_results_per_page
            params = {
                "search_query": search_query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": start,
                "max_results": max_results_per_page,
            }
            logger.info("Fetching arXiv page %d (start=%d)...", page + 1, start)

            # Retry loop with exponential backoff (up to 3 retries)
            response = None
            for attempt in range(settings.HTTP_MAX_RETRIES):
                try:
                    response = http_client.get(base_url, params=params)
                    response.raise_for_status()
                    break
                except Exception as e:
                    logger.warning(
                        "arXiv request attempt %d failed: %s",
                        attempt + 1,
                        e,
                    )
                    if attempt == settings.HTTP_MAX_RETRIES - 1:
                        raise
                    time.sleep(2.0 * (attempt + 1))

            if response is None:
                break

            page_items = parse_arxiv_feed(response.text)
            if not page_items:
                logger.info("No items returned on arXiv page %d. Stopping.", page + 1)
                break

            reached_cutoff = False
            for item in page_items:
                if item.published_at < cutoff_dt:
                    reached_cutoff = True
                    break
                if item.source_item_id in hf_metrics:
                    upvotes, comments = hf_metrics[item.source_item_id]
                    item.points = upvotes
                    item.comments = comments
                all_items.append(item)

            if reached_cutoff:
                logger.info("Reached cutoff datetime (%s). Stopping arXiv pagination.", cutoff_dt)
                break

            # Respect rate limit: 1 request every 3 seconds
            if page < max_pages - 1:
                time.sleep(3.0)

    finally:
        if owns_client:
            http_client.close()

    logger.info("Fetched a total of %d arXiv items within cutoff window.", len(all_items))
    return all_items

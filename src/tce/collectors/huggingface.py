"""Collector for Hugging Face Hub (Trending Models and Daily Papers engagement)."""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from tce.collectors.base import RawItem
from tce.settings import settings

logger = logging.getLogger(__name__)

HF_MODELS_API_URL = "https://huggingface.co/api/models"
HF_DAILY_PAPERS_API_URL = "https://huggingface.co/api/daily_papers"


def fetch_hf_daily_papers_metrics(
    client: Optional[httpx.Client] = None,
    limit: int = 100,
) -> dict[str, tuple[int, int]]:
    """Fetch recent daily papers from Hugging Face API to map arXiv IDs to (upvotes, numComments).

    Returns:
        dict mapping clean arXiv ID (e.g. '2410.29003') to tuple of (upvotes, comments_count).
    """
    owns_client = client is None
    http_client = client or httpx.Client(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )

    metrics_map: dict[str, tuple[int, int]] = {}
    try:
        response = http_client.get(HF_DAILY_PAPERS_API_URL, params={"limit": limit})
        if response.status_code == 200:
            data = response.json()
            for entry in data:
                paper = entry.get("paper") or {}
                raw_id = paper.get("id") or ""
                if not raw_id:
                    continue
                # Clean version if present (e.g. 2410.12345v1 -> 2410.12345)
                clean_id = raw_id.split("v")[0].strip()
                upvotes = int(paper.get("upvotes") or 0)
                comments = int(entry.get("numComments") or 0)
                metrics_map[clean_id] = (upvotes, comments)
            logger.info(
                "Retrieved %d arXiv paper metrics from Hugging Face Daily Papers.",
                len(metrics_map),
            )
        else:
            logger.warning(
                "Failed to fetch Hugging Face Daily Papers metrics: HTTP %d",
                response.status_code,
            )
    except Exception as e:
        logger.warning("Error fetching Hugging Face Daily Papers metrics: %s", e)
    finally:
        if owns_client:
            http_client.close()

    return metrics_map


def parse_hf_model_item(model: dict) -> Optional[RawItem]:
    """Parse a single model object from Hugging Face API into a RawItem."""
    model_id = model.get("id", "").strip()
    if not model_id:
        return None

    url = f"https://huggingface.co/{model_id}"
    pipeline_tag = model.get("pipeline_tag") or ""
    title = f"{model_id} ({pipeline_tag})" if pipeline_tag else model_id

    tags = model.get("tags") or []
    downloads = model.get("downloads") or 0
    likes = int(model.get("likes") or 0)

    # Build meaningful summary text for YAKE keyword extraction and entity matching
    summary_parts = [f"Hugging Face Model {model_id}."]
    if pipeline_tag:
        summary_parts.append(f"Task: {pipeline_tag}.")
    if downloads:
        summary_parts.append(f"Downloads: {downloads}.")
    if tags:
        summary_parts.append(f"Tags: {', '.join(str(t) for t in tags[:12])}.")
    summary = " ".join(summary_parts)

    # Parse created date
    created_at_str = model.get("createdAt")
    published_at: datetime
    if created_at_str:
        try:
            published_at = datetime.fromisoformat(
                created_at_str.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except Exception:
            published_at = datetime.now(timezone.utc)
    else:
        published_at = datetime.now(timezone.utc)

    return RawItem(
        source="hf",
        source_item_id=model_id,
        url=url,
        title=title,
        summary=summary,
        lang="en",
        published_at=published_at,
        points=likes,
        comments=0,
    )


def fetch_hf_models(
    limit: int = 50,
    sort: str = "trendingScore",
    client: Optional[httpx.Client] = None,
) -> list[RawItem]:
    """Fetch top trending models from Hugging Face Hub API."""
    owns_client = client is None
    http_client = client or httpx.Client(
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )

    items: list[RawItem] = []
    params = {
        "sort": sort,
        "limit": limit,
    }

    try:
        response = None
        for attempt in range(settings.HTTP_MAX_RETRIES):
            try:
                response = http_client.get(HF_MODELS_API_URL, params=params)
                response.raise_for_status()
                break
            except Exception as e:
                logger.warning("HF models request attempt %d failed: %s", attempt + 1, e)
                if attempt == settings.HTTP_MAX_RETRIES - 1:
                    raise
                time.sleep(1.0 * (attempt + 1))

        if response is not None and response.status_code == 200:
            data = response.json()
            for model_obj in data:
                item = parse_hf_model_item(model_obj)
                if item:
                    items.append(item)
            logger.info("Successfully fetched %d trending models from Hugging Face.", len(items))
    except Exception as e:
        logger.error("Failed to fetch models from Hugging Face: %s", e)
    finally:
        if owns_client:
            http_client.close()

    return items

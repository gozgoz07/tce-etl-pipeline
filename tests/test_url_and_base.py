"""Tests for URL normalization, hash calculation, and base item storage."""

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from tce.collectors.base import RawItem, compute_url_hash, normalize_url, store_raw_items
from tce.settings import settings


def test_normalize_url_general():
    """Verify standard URL normalization rules."""
    # Domain and scheme lowercasing, trailing slash removal
    url = "HTTPS://Example.COM/Path/To/Resource/"
    assert normalize_url(url) == "https://example.com/Path/To/Resource"

    # Fragment removal
    url_with_frag = "https://example.com/page#section-3"
    assert normalize_url(url_with_frag) == "https://example.com/page"

    # utm_* parameter removal while preserving other params
    url_with_utm = "https://example.com/article?utm_source=twitter&id=42&utm_medium=feed&sort=desc"
    normalized = normalize_url(url_with_utm)
    assert "utm_source" not in normalized
    assert "utm_medium" not in normalized
    assert "id=42" in normalized
    assert "sort=desc" in normalized


def test_normalize_url_arxiv():
    """Verify arXiv-specific URL normalization."""
    # Version stripping and conversion to abs
    assert normalize_url("https://arxiv.org/abs/2301.12345v2") == "https://arxiv.org/abs/2301.12345"
    assert normalize_url("http://arxiv.org/pdf/2301.12345v1.pdf") == "https://arxiv.org/abs/2301.12345"
    assert normalize_url("https://arxiv.org/abs/cs.AI/0101001v3") == "https://arxiv.org/abs/cs.AI/0101001"


def test_compute_url_hash():
    """Verify SHA-256 computation on normalized URL."""
    url1 = "https://example.com/article/"
    url2 = "HTTPS://example.com/article?utm_source=newsletter#heading"
    # Both normalize to https://example.com/article
    assert compute_url_hash(url1) == compute_url_hash(url2)
    expected_hash = hashlib.sha256(b"https://example.com/article").hexdigest()
    assert compute_url_hash(url1) == expected_hash


def test_raw_item_utc_enforcement():
    """Verify that RawItem ensures UTC timezone."""
    naive_dt = datetime(2026, 10, 28, 10, 0, 0)
    item = RawItem(
        source="hn",
        source_item_id="123",
        url="https://example.com/item",
        title="Test Title",
        summary="Test Summary",
        lang="en",
        published_at=naive_dt,
    )
    assert item.published_at.tzinfo == timezone.utc


def test_store_raw_items_mock():
    """Verify store_raw_items execution logic on new and updated items."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Scenario 1: New item (existing is None)
    mock_cur.fetchone.return_value = None
    items = [
        RawItem(
            source="hn",
            source_item_id="101",
            url="https://news.ycombinator.com/item?id=101",
            title="HN Item",
            summary=None,
            lang="en",
            published_at=datetime.now(timezone.utc),
            points=10,
            comments=5,
        )
    ]
    seen, new_count, updated_count = store_raw_items(items, mock_conn)
    assert seen == 1
    assert new_count == 1
    assert updated_count == 0

    # Scenario 2: Existing item update
    mock_cur.fetchone.return_value = (1, "hn", "101", "some_hash")
    seen, new_count, updated_count = store_raw_items(items, mock_conn)
    assert seen == 1
    assert new_count == 0
    assert updated_count == 1


@pytest.mark.skipif(
    not settings.TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set",
)
def test_store_raw_items_idempotence_real_db():
    """Two consecutive runs of store_raw_items insert items once, then update."""
    from tce.db import get_connection

    items = [
        RawItem(
            source="hn",
            source_item_id="test_idemp_1",
            url="https://example.com/idemp-test",
            title="Idempotence Test",
            summary="Testing idempotence",
            lang="en",
            published_at=datetime.now(timezone.utc),
            points=5,
            comments=2,
        )
    ]
    with get_connection(settings.TEST_DATABASE_URL) as conn:
        seen1, new1, upd1 = store_raw_items(items, conn)
        assert seen1 == 1
        assert new1 == 1
        assert upd1 == 0

        # Run again immediately
        seen2, new2, upd2 = store_raw_items(items, conn)
        assert seen2 == 1
        assert new2 == 0
        assert upd2 == 1

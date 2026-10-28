"""Tests for Hacker News collector parsing and filtering."""

import json
from pathlib import Path

from tce.collectors.hackernews import build_filter_predicate, parse_hn_hit, parse_hn_response


def test_parse_hn_hit_url_fallback():
    """Verify fallback to discussion item URL when url field is missing or empty."""
    hit_without_url = {
        "objectID": "12345678",
        "title": "Ask HN: What is your favorite developer tooling?",
        "url": None,
        "points": 45,
        "num_comments": 23,
        "created_at_i": 1729000000,
        "story_text": "Looking for recommendations on productivity tools.",
    }
    item = parse_hn_hit(hit_without_url)
    assert item is not None
    assert item.url == "https://news.ycombinator.com/item?id=12345678"
    assert item.source == "hn"
    assert item.source_item_id == "12345678"
    assert item.points == 45
    assert item.comments == 23
    assert item.lang == "en"


def test_build_filter_predicate():
    """Verify that predicate matches entity aliases and keywords with proper case boundaries."""
    predicate = build_filter_predicate(
        entity_aliases=["OpenAI", "RAG", "PyTorch"],
        topic_keywords=["coding agent", "vector database"],
    )

    # Matches long entity alias case-insensitively
    assert predicate("OpenAI releases new research paper")
    assert predicate("openai tools update")

    # Matches short alias case-sensitively
    assert predicate("Novel RAG architecture announced")
    assert not predicate("Cleaning with a rag cloth")

    # Matches topic keyword
    assert predicate("Building an autonomous coding agent")
    assert predicate("Setting up a Vector Database cluster")

    # Unrelated general post
    assert not predicate("Cooking tips for Italian pasta")


def test_parse_hn_response_from_fixture():
    """Verify parsing real recorded Algolia response."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "hn_sample.json"
    assert fixture_path.exists(), "tests/fixtures/hn_sample.json must exist"

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    items = parse_hn_response(data)
    assert len(items) > 0

    first = items[0]
    assert first.source == "hn"
    assert first.source_item_id != ""
    assert first.url.startswith("http")
    assert first.lang == "en"

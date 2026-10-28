"""Tests for RSS collector parsing and HTML summary cleanup."""

from pathlib import Path

from tce.collectors.rss import clean_html_summary, load_rss_sources, parse_rss_feed_content


def test_clean_html_summary():
    """Verify HTML tag stripping, entity unescaping, whitespace normalization, and truncation."""
    html_input = (
        "<p>This is a <b>bold</b> paragraph with &amp; entity &lt;brackets&gt;.</p>"
        "<div>Another section with    extra   spaces and \n newlines.</div>"
    )
    cleaned = clean_html_summary(html_input)
    assert cleaned is not None
    assert "<p>" not in cleaned
    assert "<b>" not in cleaned
    assert "&amp;" not in cleaned
    assert "&lt;" not in cleaned
    assert "&" in cleaned
    assert "<brackets>" in cleaned
    assert "\n" not in cleaned
    assert "   " not in cleaned

    # Test truncation to 1000 chars
    very_long_html = "<p>" + ("a" * 1500) + "</p>"
    truncated = clean_html_summary(very_long_html, max_chars=1000)
    assert truncated is not None
    assert len(truncated) <= 1000


def test_parse_rss_date_absent():
    """Verify fallback to collection time when published date is absent."""
    minimal_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <link>https://example.com</link>
        <description>Test</description>
        <item>
          <title>Entry Without Date</title>
          <link>https://example.com/entry-1</link>
          <description>Simple description</description>
        </item>
      </channel>
    </rss>
    """
    items = parse_rss_feed_content(minimal_rss)
    assert len(items) == 1
    assert items[0].title == "Entry Without Date"
    assert items[0].published_at is not None
    assert items[0].published_at.tzinfo is not None


def test_parse_rss_feed_from_fixture():
    """Verify parsing real recorded RSS feed."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "rss_sample.xml"
    assert fixture_path.exists(), "tests/fixtures/rss_sample.xml must exist"

    content = fixture_path.read_text(encoding="utf-8")
    items = parse_rss_feed_content(content)
    assert len(items) > 0

    first = items[0]
    assert first.source == "rss"
    assert first.url.startswith("http")
    assert first.title != ""
    if first.summary:
        assert len(first.summary) <= 1000
        assert "<p>" not in first.summary


def test_sources_yaml_exists_and_contains_examples():
    """Verify config/sources.yaml defines sample feeds."""
    sources = load_rss_sources()
    assert len(sources) >= 2, f"Expected at least 2 sample RSS feeds, found {len(sources)}"
    for s in sources:
        assert "url" in s and s["url"].startswith("http")
        assert "name" in s and s["name"]

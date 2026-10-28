"""Tests for arXiv collector parsing and data extraction."""

from pathlib import Path

from tce.collectors.arxiv import extract_arxiv_id_from_raw_id, parse_arxiv_feed


def test_extract_arxiv_id_from_raw_id():
    """Verify version removal and identifier extraction."""
    assert extract_arxiv_id_from_raw_id("http://arxiv.org/abs/2610.37668v1") == "2610.37668"
    assert extract_arxiv_id_from_raw_id("https://arxiv.org/abs/2301.12345v3") == "2301.12345"
    assert extract_arxiv_id_from_raw_id("2301.12345v2") == "2301.12345"
    assert extract_arxiv_id_from_raw_id("cs.AI/0101001v1") == "cs.AI/0101001"


def test_parse_arxiv_feed_from_fixture():
    """Verify parsing real recorded arXiv Atom feed."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "arxiv_sample.xml"
    assert fixture_path.exists(), "tests/fixtures/arxiv_sample.xml must exist"

    xml_text = fixture_path.read_text(encoding="utf-8")
    items = parse_arxiv_feed(xml_text)

    assert len(items) > 0
    first = items[0]

    # Verify ID without version
    assert not first.source_item_id.endswith("v1")
    assert not first.source_item_id.endswith("v2")
    assert first.source == "arxiv"
    assert first.url == f"https://arxiv.org/abs/{first.source_item_id}"

    # Verify title & summary whitespace normalization
    # (no multiple consecutive spaces or raw newlines)
    assert "\n" not in first.title
    assert "  " not in first.title
    assert "\n" not in first.summary
    assert "  " not in first.summary

    # Verify defaults
    assert first.lang == "en"
    assert first.points == 0
    assert first.comments == 0
    assert first.published_at is not None

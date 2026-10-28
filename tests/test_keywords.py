"""Tests for keyword extraction with YAKE and entity overlap filtering."""

from tce.enrich.entities import EntityMatcher
from tce.enrich.keywords import extract_keywords
from tce.enrich.pipeline import enrich_text


def test_extract_keywords_basic_and_max_limit():
    """Verify keyword extraction produces lowercase, deduplicated keywords up to 8 max."""
    text = (
        "Large language models and artificial intelligence architectures are transforming software "
        "engineering practices across modern cloud computing environments and systems."
    )
    keywords = extract_keywords(text, lang="en", max_keywords=8)
    assert len(keywords) > 0
    assert len(keywords) <= 8
    # All lowercase
    assert all(kw == kw.lower() for kw in keywords)
    # Deduplicated
    assert len(keywords) == len(set(keywords))


def test_extract_keywords_filters_detected_entity_aliases():
    """Verify that keywords overlapping with detected entity aliases are stripped out."""
    text = (
        "OpenAI announced a new version of ChatGPT with advanced reasoning capabilities and "
        "direct preference optimization."
    )
    # Detected entity aliases: "OpenAI", "ChatGPT"
    entity_aliases = ["OpenAI", "ChatGPT"]
    keywords = extract_keywords(text, lang="en", entity_aliases=entity_aliases)

    # Neither openai nor chatgpt should be in keywords
    assert not any("openai" in kw for kw in keywords)
    assert not any("chatgpt" in kw for kw in keywords)


def test_enrich_text_integration():
    """Verify enrich_text coordinates entity recognition and keyword extraction."""
    sample_entities = [
        {"entity_id": 42, "aliases": ["PyTorch", "Torch"]},
        {"entity_id": 99, "aliases": ["RAG", "Retrieval-Augmented Generation"]},
    ]
    matcher = EntityMatcher(sample_entities)

    title = "Fast RAG implementation using PyTorch and vector indexes"
    summary = "A practical guide to building retrieval-augmented generation pipelines."

    keywords, entity_ids = enrich_text(
        title=title,
        summary=summary,
        lang="en",
        matcher=matcher,
    )

    # Both entities should be detected
    assert 42 in entity_ids
    assert 99 in entity_ids

    # Neither "rag" nor "pytorch" should be present in keywords
    assert not any("pytorch" in kw for kw in keywords)
    assert not any("rag" in kw for kw in keywords)
    assert not any("retrieval-augmented generation" in kw for kw in keywords)

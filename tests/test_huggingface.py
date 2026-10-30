"""Unit tests for Hugging Face collector and daily papers enrichment."""

import httpx

from tce.collectors.arxiv import fetch_arxiv
from tce.collectors.huggingface import (
    fetch_hf_daily_papers_metrics,
    fetch_hf_models,
    parse_hf_model_item,
)


def test_parse_hf_model_item():
    """Verify parsing of Hugging Face model object."""
    sample_model = {
        "id": "deepseek-ai/DeepSeek-V3",
        "likes": 2450,
        "downloads": 85000,
        "trendingScore": 890,
        "pipeline_tag": "text-generation",
        "tags": ["transformers", "safetensors", "moe", "text-generation"],
        "createdAt": "2026-10-20T10:00:00.000Z",
    }

    item = parse_hf_model_item(sample_model)
    assert item is not None
    assert item.source == "hf"
    assert item.source_item_id == "deepseek-ai/DeepSeek-V3"
    assert item.url == "https://huggingface.co/deepseek-ai/DeepSeek-V3"
    assert item.title == "deepseek-ai/DeepSeek-V3 (text-generation)"
    assert item.points == 2450
    assert item.comments == 0
    assert "moe" in item.summary
    assert "85000" in item.summary
    assert item.published_at.year == 2026


def test_parse_hf_model_item_missing_id():
    """Missing model ID should return None."""
    assert parse_hf_model_item({}) is None
    assert parse_hf_model_item({"id": ""}) is None


def test_fetch_hf_daily_papers_metrics_mock():
    """Verify parsing of HF Daily Papers endpoint."""
    sample_papers = [
        {
            "paper": {
                "id": "2610.12345v1",
                "upvotes": 42,
            },
            "numComments": 8,
        },
        {
            "paper": {
                "id": "2610.99999",
                "upvotes": 5,
            },
            "numComments": 0,
        },
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_papers)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    metrics = fetch_hf_daily_papers_metrics(client=client)

    assert "2610.12345" in metrics
    assert metrics["2610.12345"] == (42, 8)
    assert "2610.99999" in metrics
    assert metrics["2610.99999"] == (5, 0)


def test_fetch_hf_models_mock():
    """Verify fetching and parsing HF models via mocked HTTP transport."""
    sample_data = [
        {
            "id": "meta-llama/Llama-3.3-70B-Instruct",
            "likes": 1200,
            "downloads": 45000,
            "pipeline_tag": "text-generation",
            "tags": ["llama-3", "text-generation"],
            "createdAt": "2026-10-21T08:00:00.000Z",
        }
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_data)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    items = fetch_hf_models(client=client)

    assert len(items) == 1
    item = items[0]
    assert item.source == "hf"
    assert item.source_item_id == "meta-llama/Llama-3.3-70B-Instruct"
    assert item.points == 1200


def test_arxiv_enriched_with_hf_metrics(monkeypatch):
    """Verify that fetch_arxiv assigns points and comments when HF metrics match."""
    from pathlib import Path
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "arxiv_sample.xml"
    xml_text = fixture_path.read_text(encoding="utf-8")

    # Mock HF Daily Papers to return metrics for the first fixture paper
    # (assuming first paper has ID 2610.37668)
    mock_metrics = {"2610.37668": (88, 14)}
    monkeypatch.setattr(
        "tce.collectors.huggingface.fetch_hf_daily_papers_metrics",
        lambda *args, **kwargs: mock_metrics,
    )

    def mock_arxiv_handler(request: httpx.Request) -> httpx.Response:
        if "arxiv.org" in str(request.url):
            return httpx.Response(200, text=xml_text)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(mock_arxiv_handler))
    items = fetch_arxiv(max_pages=1, client=client)

    assert len(items) > 0
    enriched = [it for it in items if it.source_item_id == "2610.37668"]
    assert len(enriched) == 1
    assert enriched[0].points == 88
    assert enriched[0].comments == 14

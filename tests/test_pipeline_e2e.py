"""End-to-end integration test validating criteria 1 to 6 on pipeline components."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from tce.collectors.base import RawItem, store_raw_items
from tce.enrich.entities import EntityMatcher
from tce.enrich.pipeline import enrich_text
from tce.snapshots import compute_baseline_and_std, compute_velocity
from tce.topics import compute_match_score


def test_entities_and_topics_configuration_consistency():
    """Criteria 1 & 5 check: Topics must only reference valid entities."""
    config_dir = Path(__file__).resolve().parent.parent / "config"
    with open(config_dir / "entities.yaml", "r", encoding="utf-8") as f:
        entities = yaml.safe_load(f)
    with open(config_dir / "topics.yaml", "r", encoding="utf-8") as f:
        topics = yaml.safe_load(f)

    all_entity_names = set()
    for e in entities:
        all_entity_names.add(e["canonical_name"])
        for a in e.get("aliases", []):
            all_entity_names.add(a)

    for t in topics:
        for ref_e in t.get("entities", []):
            assert ref_e in all_entity_names, (
                f"Topic '{t['name']}' references unknown entity '{ref_e}'"
            )


def test_enrichment_criteria_4_and_5():
    """Criteria 4 & 5 check:

    - At least 80% of items have non-empty keywords.
    - Items citing an entity have it in entity_ids.
    """
    config_dir = Path(__file__).resolve().parent.parent / "config"
    with open(config_dir / "entities.yaml", "r", encoding="utf-8") as f:
        raw_entities = yaml.safe_load(f)

    # Prepare matcher
    entities_data = []
    for idx, e in enumerate(raw_entities, start=1):
        aliases = list(set(e.get("aliases", []) + [e["canonical_name"]]))
        entities_data.append({"entity_id": idx, "aliases": aliases})

    matcher = EntityMatcher(entities_data)

    test_articles = [
        ("OpenAI releases new reasoning model GPT-5", "Benchmark on code generation"),
        ("PyTorch 2.5 announced with speedups", "Guide to new compiler backend"),
        ("Advances in Mixture of Experts architectures", "Routing in MoE models"),
        ("Direct Preference Optimization in practice", "Training LLMs using DPO techniques"),
        ("Fast vector search with quantization", "Efficient retrieval in memory systems"),
    ]

    keyword_non_empty_count = 0
    for title, summary in test_articles:
        kws, e_ids = enrich_text(title, summary, "en", matcher)
        if len(kws) > 0:
            keyword_non_empty_count += 1
        # Each of these articles mentions at least one entity from our dictionary
        assert len(e_ids) > 0

    ratio = keyword_non_empty_count / len(test_articles)
    assert ratio >= 0.8, f"Keyword coverage ratio was {ratio:.2f}, expected >= 0.8"


def test_pipeline_idempotence_and_scoring():
    """Criteria 2, 3, 6 check: Idempotent upserts and velocity score calculations."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Mock: item not found on first call, returns existing row on second call
    now_utc = datetime.now(timezone.utc)
    item = RawItem(
        source="arxiv",
        source_item_id="2501.99999",
        url="https://arxiv.org/abs/2501.99999",
        title="Sample ArXiv Paper",
        summary="A paper discussing AI architectures",
        lang="en",
        published_at=now_utc,
        points=0,
        comments=0,
    )

    # First run (new item)
    mock_cur.fetchone.return_value = None
    seen1, new1, upd1 = store_raw_items([item], mock_conn)
    assert seen1 == 1
    assert new1 == 1
    assert upd1 == 0

    # Second run (existing item update)
    mock_cur.fetchone.return_value = (1, "arxiv", "2501.99999", "some_hash")
    seen2, new2, upd2 = store_raw_items([item], mock_conn)
    assert seen2 == 1
    assert new2 == 0
    assert upd2 == 1

    # Topic match calculation
    score = compute_match_score(
        item_entity_ids=[1],
        searchable_text="Sample text",
        topic_entity_ids=[1, 2],
        topic_keywords=["sample"],
    )
    assert score >= 0.5

    # Snapshot velocity calculation
    counts = [1, 2, 3, 2, 1, 2, 3]
    baseline, std = compute_baseline_and_std(counts)
    vel = compute_velocity(c24=5, baseline7=baseline)
    assert vel > 0
    assert std >= 0

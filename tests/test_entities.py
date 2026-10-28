from pathlib import Path

import yaml

from tce.enrich.entities import EntityMatcher


def test_entities_yaml_count_and_types():
    """Verify that config/entities.yaml has at least 40 entities across required types."""
    entities_path = Path(__file__).resolve().parent.parent / "config" / "entities.yaml"
    assert entities_path.exists(), "config/entities.yaml must exist"

    with open(entities_path, "r", encoding="utf-8") as f:
        entities = yaml.safe_load(f)

    assert len(entities) >= 40, f"Expected >= 40 entities, found {len(entities)}"

    types = {e["type"] for e in entities}
    required_types = {"ORG", "MODEL", "PRODUCT", "LIBRARY", "TECHNIQUE"}
    assert required_types.issubset(types), f"Missing required types: {required_types - types}"

    # Verify each entity has canonical_name and aliases
    for e in entities:
        assert "canonical_name" in e and e["canonical_name"]
        assert "type" in e and e["type"]
        assert "aliases" in e and isinstance(e["aliases"], list) and len(e["aliases"]) > 0


def test_entity_matcher_case_and_word_boundaries():
    """Verify EntityMatcher case rules and boundary constraints."""
    sample_entities = [
        {"entity_id": 1, "aliases": ["OpenAI", "Open AI"]},
        {"entity_id": 2, "aliases": ["RAG", "Retrieval-Augmented Generation"]},
        {"entity_id": 3, "aliases": ["JAX"]},
        {"entity_id": 4, "aliases": ["PyTorch", "Torch"]},
        {"entity_id": 5, "aliases": ["Claude 3.5 Sonnet", "Claude 3.5"]},
    ]
    matcher = EntityMatcher(sample_entities)

    # 1. Long alias case-insensitive
    ids, aliases = matcher.extract("We love using openai and pytorch for experiments.")
    assert 1 in ids  # OpenAI
    assert 4 in ids  # PyTorch
    assert any("openai" in a.lower() for a in aliases)

    # 2. Short alias case-sensitive (length <= 3)
    # "RAG" should match, but "rag" in lowercase should not
    ids_rag_caps, _ = matcher.extract("Building a modular RAG pipeline.")
    assert 2 in ids_rag_caps

    ids_rag_lower, _ = matcher.extract("He used an old rag to clean the table.")
    assert 2 not in ids_rag_lower

    # "JAX" should match, "jax" should not
    ids_jax_caps, _ = matcher.extract("Compiling code with JAX.")
    assert 3 in ids_jax_caps

    ids_jax_lower, _ = matcher.extract("Exploring jax library.")
    assert 3 not in ids_jax_lower

    # 3. Word boundary: "FRAGILE" or "STORAGE" must not match "RAG"
    ids_fragile, _ = matcher.extract("This is a FRAGILE package in STORAGE.")
    assert 2 not in ids_fragile

    # 4. Longest alias matched
    ids_claude, aliases_claude = matcher.extract("Anthropic just released Claude 3.5 Sonnet today.")
    assert 5 in ids_claude
    assert "Claude 3.5 Sonnet" in aliases_claude

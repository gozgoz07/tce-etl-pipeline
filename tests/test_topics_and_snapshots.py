"""Tests for topic match scoring, attachment rules, and snapshot calculations."""

import pytest

from tce.snapshots import compute_baseline_and_std, compute_velocity
from tce.topics import compute_match_score


def test_topic_match_score_rules():
    """Verify attachment rules:

    - One entity hit gives 0.5 (meets threshold 0.5).
    - One keyword hit gives 0.25 (does NOT meet threshold 0.5).
    - Two keyword hits give 0.5 (meets threshold 0.5).
    - Score is capped at 1.0.
    """
    topic_entities = [10, 20]
    topic_keywords = ["coding agent", "code generation", "autonomous agent"]

    # 1. One entity hit alone
    score_one_entity = compute_match_score(
        item_entity_ids=[10],
        searchable_text="Some unrelated article text without keywords",
        topic_entity_ids=topic_entities,
        topic_keywords=topic_keywords,
    )
    assert score_one_entity == 0.5
    assert score_one_entity >= 0.5  # Sufficient to attach!

    # 2. One keyword hit alone
    score_one_keyword = compute_match_score(
        item_entity_ids=[],
        searchable_text="An article introducing a new coding agent tool.",
        topic_entity_ids=topic_entities,
        topic_keywords=topic_keywords,
    )
    assert score_one_keyword == 0.25
    assert score_one_keyword < 0.5  # NOT sufficient to attach!

    # 3. Two keyword hits
    score_two_keywords = compute_match_score(
        item_entity_ids=[],
        searchable_text="Advances in code generation for building a coding agent.",
        topic_entity_ids=topic_entities,
        topic_keywords=topic_keywords,
    )
    assert score_two_keywords == 0.5
    assert score_two_keywords >= 0.5  # Sufficient to attach!

    # 4. Multiple entities and keywords capped at 1.0
    score_max = compute_match_score(
        item_entity_ids=[10, 20, 30],
        searchable_text="coding agent and code generation and autonomous agent everywhere",
        topic_entity_ids=topic_entities,
        topic_keywords=topic_keywords,
    )
    assert score_max == 1.0


def test_compute_baseline_and_std():
    """Verify 7-day baseline and population standard deviation calculations."""
    counts = [2, 2, 2, 2, 2, 2, 2]
    baseline, std = compute_baseline_and_std(counts)
    assert baseline == 2.0
    assert std == 0.0

    # Non-constant daily counts
    # Mean: (1 + 2 + 3 + 4 + 5 + 6 + 7) / 7 = 28 / 7 = 4.0
    counts_linear = [1, 2, 3, 4, 5, 6, 7]
    baseline_lin, std_lin = compute_baseline_and_std(counts_linear)
    assert baseline_lin == 4.0
    # Variance = (9 + 4 + 1 + 0 + 1 + 4 + 9) / 7 = 28 / 7 = 4.0 => std = 2.0
    assert pytest.approx(std_lin, 0.001) == 2.0


def test_compute_velocity_synthetic():
    """Verify velocity score calculation matches spec example.

    Spec: c24 = 6 and baseline7 = 2 give (6 + 1) / (2 + 1) = 7 / 3 ≈ 2.333.
    """
    c24 = 6
    baseline7 = 2.0
    vel = compute_velocity(c24, baseline7)
    assert pytest.approx(vel, 0.001) == 2.3333333333333335
    assert round(vel, 3) == 2.333

    # Edge case: zero items today and zero baseline
    vel_zero = compute_velocity(0, 0.0)
    assert vel_zero == 1.0

"""Daily topic snapshot computation and report generation."""

import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import psycopg

logger = logging.getLogger(__name__)


def compute_velocity(c24: int, baseline7: float) -> float:
    """Compute velocity score: (c24 + 1) / (baseline7 + 1)."""
    return (c24 + 1.0) / (baseline7 + 1.0)


def compute_baseline_and_std(counts: list[int]) -> tuple[float, float]:
    """Compute baseline (mean) and population standard deviation of 7 counts."""
    if len(counts) != 7:
        raise ValueError(f"Expected exactly 7 daily counts, got {len(counts)}")
    baseline = sum(counts) / 7.0
    variance = sum((x - baseline) ** 2 for x in counts) / 7.0
    std = math.sqrt(variance)
    return baseline, std


def generate_snapshots(
    conn: psycopg.Connection,
    target_date: Optional[date] = None,
) -> int:
    """Compute daily snapshot and velocity score for all topics on target_date.

    Target date defaults to yesterday UTC. Upserts into topic_snapshots table.
    """
    if target_date is None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    # Check if we have at least 7 days of history before target_date
    history_start = day_start - timedelta(days=7)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(published_at) FROM items WHERE published_at < %s",
            (day_start,),
        )
        min_pub = cur.fetchone()[0]
        if min_pub is None or min_pub > history_start:
            logger.warning(
                "Fewer than 7 days of items exist before %s. Score is preliminary.",
                target_date,
            )

        # Get all topics
        cur.execute("SELECT topic_id, name FROM topics")
        topics = cur.fetchall()

        if not topics:
            logger.warning("No topics found in database.")
            return 0

        snapshot_count = 0
        for topic_id, _name in topics:
            # 1. Day D metrics
            cur.execute(
                """
                SELECT
                    COUNT(i.item_id) AS c24,
                    COUNT(DISTINCT i.source) AS distinct_sources,
                    COALESCE(SUM(i.points + i.comments), 0) AS engagement_sum
                FROM item_topics it
                JOIN items i ON it.item_id = i.item_id
                WHERE it.topic_id = %s
                  AND i.published_at >= %s
                  AND i.published_at < %s
                """,
                (topic_id, day_start, day_end),
            )
            row = cur.fetchone()
            c24 = row[0] or 0
            distinct_sources = row[1] or 0
            engagement_sum = row[2] or 0

            # 2. 7 preceding daily counts (D-7 to D-1)
            past_counts: list[int] = []
            for d in range(7, 0, -1):
                p_start = day_start - timedelta(days=d)
                p_end = p_start + timedelta(days=1)
                cur.execute(
                    """
                    SELECT COUNT(i.item_id)
                    FROM item_topics it
                    JOIN items i ON it.item_id = i.item_id
                    WHERE it.topic_id = %s
                      AND i.published_at >= %s
                      AND i.published_at < %s
                    """,
                    (topic_id, p_start, p_end),
                )
                p_count = cur.fetchone()[0] or 0
                past_counts.append(p_count)

            baseline7, std7 = compute_baseline_and_std(past_counts)
            velocity_score = compute_velocity(c24, baseline7)

            # 3. Upsert into topic_snapshots
            cur.execute(
                """
                INSERT INTO topic_snapshots (
                    topic_id, snapshot_date, c24, baseline7, std7,
                    distinct_sources, engagement_sum, velocity_score
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (topic_id, snapshot_date) DO UPDATE SET
                    c24 = EXCLUDED.c24,
                    baseline7 = EXCLUDED.baseline7,
                    std7 = EXCLUDED.std7,
                    distinct_sources = EXCLUDED.distinct_sources,
                    engagement_sum = EXCLUDED.engagement_sum,
                    velocity_score = EXCLUDED.velocity_score
                """,
                (
                    topic_id,
                    target_date,
                    c24,
                    round(baseline7, 3),
                    round(std7, 3),
                    distinct_sources,
                    engagement_sum,
                    round(velocity_score, 3),
                ),
            )
            snapshot_count += 1

    logger.info("Generated %d snapshots for date %s", snapshot_count, target_date)
    return snapshot_count


def get_top_topics_report(
    conn: psycopg.Connection,
    target_date: Optional[date] = None,
    limit: int = 10,
) -> list[dict]:
    """Retrieve top topics ranked by velocity score for target_date."""
    if target_date is None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                t.name,
                s.c24,
                s.baseline7,
                s.std7,
                s.distinct_sources,
                s.engagement_sum,
                s.velocity_score
            FROM topic_snapshots s
            JOIN topics t ON s.topic_id = t.topic_id
            WHERE s.snapshot_date = %s
            ORDER BY s.velocity_score DESC, s.c24 DESC
            LIMIT %s
            """,
            (target_date, limit),
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        results.append({
            "name": row[0],
            "c24": row[1],
            "baseline7": float(row[2]),
            "std7": float(row[3]),
            "distinct_sources": row[4],
            "engagement_sum": row[5],
            "velocity_score": float(row[6]),
        })
    return results

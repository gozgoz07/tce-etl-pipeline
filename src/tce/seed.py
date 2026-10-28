"""Database seeding from YAML configuration files."""

import logging
from pathlib import Path
from typing import Optional

import psycopg
import yaml

from tce.settings import settings

logger = logging.getLogger(__name__)


def seed_entities(conn: psycopg.Connection, file_path: Optional[Path] = None) -> int:
    """Load entities.yaml into entities table with alias merging and validated status."""
    path = file_path or (settings.CONFIG_DIR / "entities.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Entities file not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected list of entities in {path}, got {type(data)}")

    inserted_or_updated = 0
    with conn.cursor() as cur:
        for entry in data:
            canonical_name = entry.get("canonical_name", "").strip()
            entity_type = entry.get("type", "").strip()
            aliases = entry.get("aliases", [])
            if not canonical_name or not entity_type:
                logger.warning("Skipping invalid entity entry: %s", entry)
                continue

            cur.execute(
                """
                INSERT INTO entities (canonical_name, type, aliases, status)
                VALUES (%s, %s, %s, 'validated')
                ON CONFLICT (canonical_name, type) DO UPDATE SET
                    aliases = (
                        SELECT COALESCE(array_agg(DISTINCT x), '{}')
                        FROM unnest(entities.aliases || EXCLUDED.aliases) AS x
                    ),
                    status = 'validated'
                """,
                (canonical_name, entity_type, aliases),
            )
            inserted_or_updated += 1

    logger.info("Seeded %d entities from %s", inserted_or_updated, path)
    return inserted_or_updated


def seed_topics(conn: psycopg.Connection, file_path: Optional[Path] = None) -> int:
    """Load topics.yaml into topics table.

    Fails if any referenced entity does not exist in entities table.
    """
    path = file_path or (settings.CONFIG_DIR / "topics.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Topics file not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected list of topics in {path}, got {type(data)}")

    with conn.cursor() as cur:
        # Load all canonical names and their entity_id
        cur.execute("SELECT entity_id, canonical_name FROM entities")
        entity_name_to_id = {row[1]: row[0] for row in cur.fetchall()}

        # Also map all aliases to entity_id for flexibility
        cur.execute("SELECT entity_id, unnest(aliases) FROM entities")
        for e_id, alias in cur.fetchall():
            entity_name_to_id[alias] = e_id

        seeded_topics = 0
        for entry in data:
            topic_name = entry.get("name", "").strip()
            category = entry.get("category", "tech").strip()
            keywords = entry.get("keywords", [])
            entity_names = entry.get("entities", [])

            if not topic_name:
                continue

            # Validate that every entity exists
            resolved_entity_ids = []
            for e_name in entity_names:
                if e_name not in entity_name_to_id:
                    raise ValueError(
                        f"Topic '{topic_name}' references missing entity '{e_name}'"
                    )
                resolved_entity_ids.append(entity_name_to_id[e_name])

            # Deduplicate and sort entity IDs
            resolved_entity_ids = sorted(list(set(resolved_entity_ids)))

            cur.execute(
                """
                INSERT INTO topics (name, category, keywords, entity_ids)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    category = EXCLUDED.category,
                    keywords = EXCLUDED.keywords,
                    entity_ids = EXCLUDED.entity_ids
                """,
                (topic_name, category, keywords, resolved_entity_ids),
            )
            seeded_topics += 1

    logger.info("Seeded %d topics from %s", seeded_topics, path)
    return seeded_topics


def seed_all(
    conn: psycopg.Connection,
    entities_path: Optional[Path] = None,
    topics_path: Optional[Path] = None,
) -> tuple[int, int]:
    """Seed both entities and topics in order."""
    num_entities = seed_entities(conn, entities_path)
    num_topics = seed_topics(conn, topics_path)
    return num_entities, num_topics

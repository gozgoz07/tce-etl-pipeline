"""Entity extraction using alias dictionary and regular expressions."""

import logging
import re
from typing import Optional, Sequence

import psycopg

logger = logging.getLogger(__name__)


class EntityMatcher:
    """Matches text against a dictionary of entity aliases according to V0 rules."""

    def __init__(self, entities: Sequence[dict]) -> None:
        """Initialize matcher with a list of entities.

        Each entity dict is expected to have:
            - 'entity_id': int
            - 'aliases': list of str
        """
        self.entities = entities

        # Split aliases into short (<= 3 chars, case-sensitive)
        # and long (> 3 chars, case-insensitive)
        self.short_alias_to_id: dict[str, int] = {}
        self.long_alias_to_id: dict[str, int] = {}

        short_aliases: list[str] = []
        long_aliases: list[str] = []

        for entity in entities:
            e_id = entity["entity_id"]
            for alias in entity.get("aliases", []):
                alias_str = alias.strip()
                if not alias_str:
                    continue
                if len(alias_str) <= 3:
                    self.short_alias_to_id[alias_str] = e_id
                    short_aliases.append(alias_str)
                else:
                    self.long_alias_to_id[alias_str.lower()] = e_id
                    long_aliases.append(alias_str)

        # Sort from longest to shortest
        short_aliases.sort(key=len, reverse=True)
        long_aliases.sort(key=len, reverse=True)

        # Compile regexes with word boundaries (?<!\w) ... (?!\w)
        if short_aliases:
            pattern_short = r"(?<!\w)(" + "|".join(re.escape(a) for a in short_aliases) + r")(?!\w)"
            self.regex_short: Optional[re.Pattern] = re.compile(pattern_short)
        else:
            self.regex_short = None

        if long_aliases:
            pattern_long = r"(?<!\w)(" + "|".join(re.escape(a) for a in long_aliases) + r")(?!\w)"
            self.regex_long: Optional[re.Pattern] = re.compile(pattern_long, re.IGNORECASE)
        else:
            self.regex_long = None

    @classmethod
    def from_db(cls, conn: psycopg.Connection) -> "EntityMatcher":
        """Load validated entities and their aliases from database."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_id, canonical_name, aliases
                FROM entities
                WHERE status = 'validated'
                """
            )
            rows = cur.fetchall()

        entities = []
        for entity_id, canonical_name, aliases in rows:
            # Include canonical_name in aliases if not already present
            all_aliases = set(aliases or [])
            all_aliases.add(canonical_name)
            entities.append({
                "entity_id": entity_id,
                "aliases": list(all_aliases),
            })
        return cls(entities)

    def extract(self, text: str) -> tuple[list[int], list[str]]:
        """Extract matching entity_ids and matched alias strings from text.

        Returns:
            (sorted_deduplicated_entity_ids, matched_alias_strings)
        """
        if not text:
            return [], []

        matched_ids: set[int] = set()
        matched_aliases: list[str] = []

        # 1. Match short aliases (case-sensitive)
        if self.regex_short:
            for match in self.regex_short.finditer(text):
                matched_str = match.group(0)
                if matched_str in self.short_alias_to_id:
                    matched_ids.add(self.short_alias_to_id[matched_str])
                    matched_aliases.append(matched_str)

        # 2. Match long aliases (case-insensitive)
        if self.regex_long:
            for match in self.regex_long.finditer(text):
                matched_str = match.group(0)
                key = matched_str.lower()
                if key in self.long_alias_to_id:
                    matched_ids.add(self.long_alias_to_id[key])
                    matched_aliases.append(matched_str)

        return sorted(matched_ids), matched_aliases

"""Keyword extraction using YAKE with entity overlap filtering."""

import logging
from typing import Optional, Sequence

import yake

logger = logging.getLogger(__name__)


def extract_keywords(
    text: str,
    lang: Optional[str] = "en",
    entity_aliases: Optional[Sequence[str]] = None,
    max_keywords: int = 8,
) -> list[str]:
    """Extract up to 8 keywords using YAKE, filtering out overlaps with entity aliases.

    - Uses YAKE on text (title + summary).
    - Supports specified language (defaults to 'en').
    - n-grams of 1 to 2 words.
    - Filters out any keyword that overlaps with a detected entity alias (case-insensitive).
    - Lowercases, deduplicates, and limits to max_keywords.
    """
    cleaned_text = (text or "").strip()
    if not cleaned_text:
        return []

    # Map / normalize language for YAKE
    safe_lang = (lang or "en").lower()
    if safe_lang not in ("en", "fr", "es", "de", "it", "pt"):
        safe_lang = "en"

    try:
        kw_extractor = yake.KeywordExtractor(
            lan=safe_lang,
            n=2,
            top=max_keywords * 2,  # Extract extra candidates to allow filtering
            windowsSize=1,
        )
        extracted = kw_extractor.extract_keywords(cleaned_text)
    except Exception as e:
        logger.warning("YAKE extraction failed for lang=%s: %s", safe_lang, e)
        return []

    aliases_lower = [a.lower().strip() for a in (entity_aliases or []) if a.strip()]

    def overlaps_with_entity(kw_str: str) -> bool:
        kw_lower = kw_str.lower()
        for alias in aliases_lower:
            if kw_lower == alias or kw_lower in alias or alias in kw_lower:
                return True
        return False

    final_keywords: list[str] = []
    seen: set[str] = set()

    for kw, _score in extracted:
        clean_kw = kw.strip().lower()
        if not clean_kw or clean_kw in seen:
            continue
        if overlaps_with_entity(clean_kw):
            continue

        seen.add(clean_kw)
        final_keywords.append(clean_kw)
        if len(final_keywords) >= max_keywords:
            break

    return final_keywords

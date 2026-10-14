"""Text normalisation shared by the EPUB reader, horizon anchors and quote check.

Keep this small and dependency-free: the same rules must be reimplemented in
TypeScript for the PWA (fingerprints are compared across the two).
"""

from __future__ import annotations

import re
import unicodedata

# Invisible characters that EPUBs sprinkle into text (SE uses U+FEFF before
# dashes as a word joiner).
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)
_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"'})
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)

FINGERPRINT_WORDS = 12


def clean(text: str) -> str:
    """Remove invisible characters and collapse whitespace. Used for stored text."""
    return _WS_RE.sub(" ", text.translate(_INVISIBLE)).strip()


def clean_paragraphs(text: str) -> str:
    """Like ``clean`` but keeps paragraph breaks (blank lines) for display."""
    paras = (clean(p) for p in re.split(r"\n\s*\n", text))
    return "\n\n".join(p for p in paras if p)


def fold(text: str) -> str:
    """Lower-case, strip accents, straighten quotes. Used for matching only."""
    text = clean(text).translate(_QUOTES).lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def words(text: str) -> list[str]:
    return _WORD_RE.findall(fold(text))


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def fingerprint(text: str, n: int = FINGERPRINT_WORDS) -> str:
    """Stable, edition-tolerant fingerprint: the first ``n`` folded words."""
    return " ".join(words(text)[:n])

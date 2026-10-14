"""Quote-or-drop: locate an LLM-provided quote verbatim in its evidence passage.

LLMs reproduce quotes with small differences (straight vs curly quotes,
whitespace). ``locate_quote`` tolerates exactly those, and returns offsets into
the *stored* passage text so the pack stores the passage's own characters.
The pack's trigger then re-checks the span mechanically on insert.
"""

from __future__ import annotations

import unicodedata

MIN_QUOTE_WORDS = 3

_EQUIV = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-", "–": "-"})


def _canon_char(c: str) -> str:
    c = c.translate(_EQUIV)
    return "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))


def _canonical_with_map(text: str) -> tuple[str, list[int]]:
    """Canonicalise ``text`` and map each output char back to its source index."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch.isspace() or ch in "­​⁠﻿":
            if ch.isspace() and not prev_space:
                out.append(" ")
                index.append(i)
                prev_space = True
            continue
        for c in _canon_char(ch).lower():
            out.append(c)
            index.append(i)
        prev_space = False
    return "".join(out), index


def locate_quote(passage_text: str, quote: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` offsets of ``quote`` in ``passage_text``, or None."""
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return None
    exact = passage_text.find(quote)
    if exact >= 0:
        return exact, exact + len(quote)
    hay, index = _canonical_with_map(passage_text)
    needle, _ = _canonical_with_map(quote.strip().strip("\"'“”‘’"))
    needle = needle.strip()
    if len(needle.split()) < MIN_QUOTE_WORDS:
        return None
    at = hay.find(needle)
    if at < 0:
        return None
    return index[at], index[at + len(needle) - 1] + 1


def quote_verifies(passage_text: str, quote_span: str, start: int, end: int) -> bool:
    """The mechanical check the pack trigger also performs."""
    return passage_text[start:end] == quote_span and end > start

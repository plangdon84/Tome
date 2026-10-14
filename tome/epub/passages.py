"""Split a chapter's paragraphs into passages of about 150-400 words."""

from __future__ import annotations

import re

from tome.text import word_count

MIN_WORDS = 150
TARGET_WORDS = 250
MAX_WORDS = 400
# Paragraphs longer than this are cut at sentence boundaries first, so that a
# short running passage plus one unit never overshoots MAX_WORDS.
UNIT_MAX = 200

_SENTENCE_END = re.compile(r"(?<=[.!?…])[”’\"')\]]*\s+(?=[“‘\"'(\[A-Z0-9])")


def _sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        out.append(text[start : m.end()].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


def _units(paragraph: str) -> list[str]:
    """Break an over-long paragraph into chunks of at most ~UNIT_MAX words."""
    if word_count(paragraph) <= UNIT_MAX:
        return [paragraph]
    chunks, cur, cur_n = [], [], 0
    for sentence in _sentences(paragraph):
        n = word_count(sentence)
        if n > UNIT_MAX:  # a monster sentence: hard split on words
            ws = sentence.split()
            pieces = [" ".join(ws[i : i + UNIT_MAX]) for i in range(0, len(ws), UNIT_MAX)]
        else:
            pieces = [sentence]
        for piece in pieces:
            pn = word_count(piece)
            if cur and cur_n + pn > UNIT_MAX:
                chunks.append(" ".join(cur))
                cur, cur_n = [], 0
            cur.append(piece)
            cur_n += pn
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def split_passages(
    paragraphs: list[str],
    *,
    min_words: int = MIN_WORDS,
    target_words: int = TARGET_WORDS,
    max_words: int = MAX_WORDS,
) -> list[str]:
    units = [u for p in paragraphs for u in _units(p) if u.strip()]
    passages: list[list[str]] = []
    cur: list[str] = []
    cur_n = 0
    for unit in units:
        n = word_count(unit)
        if cur and cur_n >= min_words and cur_n + n > max_words:
            passages.append(cur)
            cur, cur_n = [], 0
        cur.append(unit)
        cur_n += n
        if cur_n >= target_words:
            passages.append(cur)
            cur, cur_n = [], 0
    if cur:
        if passages and cur_n < min_words:
            prev = passages.pop()
            merged = prev + cur
            if sum(map(word_count, merged)) <= max_words:
                passages.append(merged)
            else:
                passages.extend(_rebalance(merged))
        else:
            passages.append(cur)
    return ["\n\n".join(p) for p in passages]


def _rebalance(units: list[str]) -> list[list[str]]:
    """Split units into two parts of roughly equal word count."""
    total = sum(map(word_count, units))
    first, n = [], 0
    for i, unit in enumerate(units):
        if first and n >= total / 2:
            return [first, units[i:]]
        first.append(unit)
        n += word_count(unit)
    return [first]

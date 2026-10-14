"""Baseline reading-time answerer: database lookups only, no LLM.

This is a deliberately thin Phase 0 stand-in for the Phase 3 query pipeline,
so the eval harness can check "what the app would show". It only ever talks
to a ``HorizonReader``, so it cannot see past the horizon.

Pipeline: match entity names in the question (aliases visible at the
horizon) -> who/what lookups (latest profile, newer observations,
relationships, revealed identities) -> recap lookups -> anticipated Q&A by
word overlap -> keyword passage search as a "possibly relevant" fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from tome.horizon import HorizonReader
from tome.text import fold, words

RECAP_RE = re.compile(r"\b(recap|so far|what happened|summar)", re.I)
STOPWORDS = frozenset(
    "a an and are as at be but by did do does for from had has have he her him his how i if in "
    "is it its me my of on or she so than that the their them then there they this to was we "
    "were what when where which who whom why will with you your".split()
)
QA_MIN_OVERLAP = 0.5
# Default posture is "what the text has shown to be true". Inferences are only
# offered when the question itself asks for speculation (DECISIONS.md §9).
SPECULATIVE_RE = re.compile(
    r"\b(might|could|maybe|perhaps|suspect\w*|theor\w*|guess\w*|possibl\w*|"
    r"speculat\w*|likely|hint\w*|clues?)\b",
    re.I,
)


@dataclass
class Piece:
    kind: str  # 'profile', 'observation', 'relationship', 'summary', ...
    text: str
    max_source_pos: int
    evidence_pos: list[int] = field(default_factory=list)


@dataclass
class Answer:
    question: str
    horizon: int
    entities: list[str]
    pieces: list[Piece]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pieces)

    def max_pos(self) -> int:
        return max(
            [0]
            + [p.max_source_pos for p in self.pieces]
            + [e for p in self.pieces for e in p.evidence_pos]
        )


def match_entities(reader: HorizonReader, question: str) -> list[tuple[str, int]]:
    """(surface form, entity_id) pairs found in the question, longest first."""
    q = " " + " ".join(words(question)) + " "
    taken: list[tuple[int, int]] = []
    found = []
    for alias in reader.aliases():  # longest first
        needle = " " + alias["normalized"] + " "
        start = q.find(needle)
        while start >= 0:
            span = (start, start + len(needle))
            if not any(s < span[1] and span[0] < e for s, e in taken):
                taken.append(span)
                found.append((alias["surface_form"], alias["entity_id"]))
                break
            start = q.find(needle, start + 1)
    return found


def _identity_closure(reader: HorizonReader, entity_id: int) -> list[int]:
    seen, todo = [entity_id], [entity_id]
    while todo:
        for other in reader.identities(todo.pop()):
            if other not in seen:
                seen.append(other)
                todo.append(other)
    return seen


def is_speculative(question: str) -> bool:
    return bool(SPECULATIVE_RE.search(question))


def _entity_pieces(
    reader: HorizonReader, entity_id: int, *, speculative: bool = False
) -> list[Piece]:
    pieces = []
    profile = reader.latest_profile(entity_id)
    since = 0
    if profile:
        pieces.append(Piece("profile", profile["profile_text"], profile["max_source_pos"]))
        since = profile["max_source_pos"]
    for o in reader.observations(entity_id, since_pos=since, include_inferred=speculative):
        if o["status"] == "claimed":
            # A claim is shown as a claim, attributed, never as fact.
            names = reader.names(o["claimed_by_entity_id"]) if o["claimed_by_entity_id"] else []
            prefix = f"({names[0] if names else 'someone'} claims) "
        elif o["status"] == "inferred":
            prefix = "(inference, not confirmed by the text) "
        else:
            prefix = ""
        pieces.append(
            Piece("observation", prefix + o["sentence"], o["max_source_pos"], [o["evidence_pos"]])
        )
    for r in reader.relationships(entity_id):
        pieces.append(Piece("relationship", r["description"], r["max_source_pos"], [r["pos"]]))
    return pieces


def _content_words(text: str) -> set[str]:
    return {w for w in words(text) if w not in STOPWORDS}


def answer(reader: HorizonReader, question: str, *, max_passages: int = 3) -> Answer:
    pieces: list[Piece] = []
    speculative = is_speculative(question)
    matched = match_entities(reader, question)
    seen_entities: list[int] = []
    for _, entity_id in matched:
        for eid in _identity_closure(reader, entity_id):
            if eid in seen_entities:
                continue
            seen_entities.append(eid)
            if eid != entity_id:
                names = reader.names(eid)
                if names:
                    pieces.append(
                        Piece("identity", f"Also known as: {', '.join(names)}.", reader.horizon)
                    )
            pieces.extend(_entity_pieces(reader, eid, speculative=speculative))

    if RECAP_RE.search(question) and not matched:
        rollup = reader.latest_rollup()
        if rollup:
            pieces.append(Piece("rollup", rollup["text"], rollup["max_source_pos"]))
        for s in reader.chapter_summaries(limit=3):
            pieces.append(Piece("summary", s["summary_text"], s["max_source_pos"]))

    q_words = _content_words(question)
    for qa in reader.anticipated_qa():
        qa_words = _content_words(qa["question"])
        if qa_words and q_words and len(q_words & qa_words) / len(qa_words) >= QA_MIN_OVERLAP:
            cited = json.loads(qa["evidence_passage_ids"])
            cited_pos = [p["pos"] for pid in cited if (p := reader.passage(pid))]
            pieces.append(Piece("anticipated_qa", qa["answer"], qa["max_source_pos"], cited_pos))

    if not pieces:
        for p in reader.search_passages(question, limit=max_passages):
            pieces.append(Piece("passage", p["text"], p["pos"], [p["pos"]]))

    return Answer(question, reader.horizon, [fold(s) for s, _ in matched], pieces)

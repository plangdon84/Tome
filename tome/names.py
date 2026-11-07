"""Catch names in a summary that the text has not used yet.

A summary may only use what the reader has seen, so a capitalized word the text
has not used by that point most likely came from the model's memory of the book.
This catches new names only: it can't catch a wrong fact about a known name.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_SENTENCE_END = ".!?:\n"
_OPENING = " \t\"'“‘(["
# Words summaries open sentences with that a book may not have used yet. Never
# add a word here that could be a name.
_OPENERS = frozenset(
    "after afterward afterwards although despite eventually finally however later "
    "meanwhile nevertheless soon subsequently suddenly throughout together upon".split()
)


def _base(word: str) -> str:
    return re.sub(r"['’]s$", "", word)


class TextVocabulary:
    """The words of the text so far, added in reading order."""

    def __init__(self) -> None:
        self._capitalized: set[str] = set()
        self._lowered: set[str] = set()

    def add(self, text: str) -> None:
        for match in _WORD.finditer(text):
            word = _base(match.group())
            self._lowered.add(word.lower())
            if word[0].isupper():
                self._capitalized.add(word.title() if word.isupper() else word)

    def unseen_names(self, summary: str) -> list[str]:
        """Capitalized words of ``summary`` the text hasn't used, in order of appearance.

        Mid-sentence, the word must have been capitalized in the text, so the
        surname "Gale" isn't excused by a lowercase "gale". The first word of a
        sentence is capitalized anyway, so any use in the text counts, as does a
        common opener such as "Despite".
        """
        found: dict[str, None] = {}
        for match in _WORD.finditer(summary):
            word = _base(match.group())
            if not word[0].isupper():
                continue
            before = summary[: match.start()].rstrip(_OPENING)
            starts_sentence = not before or before[-1] in _SENTENCE_END
            if starts_sentence:
                known = word.lower() in self._lowered or word.lower() in _OPENERS
            else:
                known = (word.title() if word.isupper() else word) in self._capitalized
            if not known:
                found[word] = None
        return list(found)

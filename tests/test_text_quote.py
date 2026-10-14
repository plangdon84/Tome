from tome.quote import locate_quote, quote_verifies
from tome.text import clean, fingerprint, fold, word_count

PASSAGE = "“Ah, is it you, Dantès?” cried the man in the skiff.\n\n“What’s the matter?”"


def test_clean_strips_invisible_characters():
    assert clean("Marseilles﻿—The  Arrival\n") == "Marseilles—The Arrival"


def test_fold_and_fingerprint_are_accent_and_quote_insensitive():
    assert fold("Château d’If") == "chateau d'if"
    assert fingerprint("“Ah, is it you, Dantès?”") == "ah is it you dantes"
    assert word_count("What’s the matter?") == 3


def test_locate_exact_quote():
    start, end = locate_quote(PASSAGE, "cried the man in the skiff")
    assert PASSAGE[start:end] == "cried the man in the skiff"


def test_locate_quote_tolerates_straight_quotes_and_whitespace():
    span = locate_quote(PASSAGE, '"Ah, is it you,   Dantes?" cried')
    assert span is not None
    start, end = span
    assert PASSAGE[start:end] == "Ah, is it you, Dantès?” cried"
    assert quote_verifies(PASSAGE, PASSAGE[start:end], start, end)


def test_locate_quote_rejects_invented_or_tiny_quotes():
    assert locate_quote(PASSAGE, "said the man in the boat") is None
    assert locate_quote(PASSAGE, "Dantès") is None  # too short to be evidence
    assert locate_quote(PASSAGE, "the matter? cried the man") is None

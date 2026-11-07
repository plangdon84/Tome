"""Names a summary uses before the text has used them are caught."""

from tome.names import TextVocabulary


def _vocabulary(text: str) -> TextVocabulary:
    v = TextVocabulary()
    v.add(text)
    return v


def test_name_from_memory_is_caught_mid_sentence_and_at_a_sentence_start():
    v = _vocabulary("Dorothy lived in Kansas.")
    assert v.unseen_names("Dorothy Gale lived in Kansas. Glinda helped.") == ["Gale", "Glinda"]


def test_lowercase_word_in_the_text_does_not_excuse_a_surname():
    assert _vocabulary("Dorothy felt a gale.").unseen_names("Dorothy Gale left.") == ["Gale"]


def test_sentence_start_only_needs_the_word_used():
    assert _vocabulary("they walked on.").unseen_names("They walked on.") == []


def test_common_openers_are_allowed():
    assert _vocabulary("Dorothy left.").unseen_names("Meanwhile, Dorothy left.") == []


def test_possessive_all_caps_title_and_quotes():
    v = _vocabulary("THE SCARECROW. she saw Dorothy’s dog ran.")
    assert v.unseen_names("Dorothy's dog saw the Scarecrow.") == []
    assert v.unseen_names('She said, "Oz waits."') == ["Oz"]


def test_each_name_is_listed_once():
    v = _vocabulary("nobody")
    assert v.unseen_names("Then Oz spoke, and Oz's voice rose.") == ["Then", "Oz"]

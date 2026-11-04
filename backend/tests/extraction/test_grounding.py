"""The grounding check (#23): quote found after normalisation, accented and CJK text, length,
the redaction mark, and the support of the value by its quote. No database."""

import pytest

from app.extraction.grounding import (
    MAX_QUOTE_CHARS,
    is_redacted_quote,
    normalise,
    quote_in_text,
    quote_long_enough,
    value_supported,
)
from app.extraction.stage import chunks


def found(quote: str, text: str) -> bool:
    return quote_in_text(quote, normalise(text))


def test_a_verbatim_quote_is_found() -> None:
    assert found("founded in 2005", "Acme was founded in 2005 in Lyon.")


def test_a_quote_not_in_the_text_is_not_found() -> None:
    assert not found("founded in 2006", "Acme was founded in 2005 in Lyon.")


def test_an_empty_quote_is_not_found() -> None:
    assert not found("   ", "Acme was founded in 2005.")


def test_whitespace_and_line_breaks_are_normalised() -> None:
    text = "Acme was\n   founded in\t2005."
    assert found("Acme was founded in 2005.", text)
    assert found("Acme   was\nfounded in 2005.", "Acme was founded in 2005.")


@pytest.mark.parametrize(
    ("quote", "text"),
    [
        ("l'entreprise familiale", "Une société : l’entreprise familiale depuis 1950."),
        ("l’entreprise familiale", "Une société : l'entreprise familiale depuis 1950."),
        ("«qualité» et service", "une “qualité” et service"),
        ("2005 - 2010", "de 2005 – 2010 environ"),
        ("2005 — 2010", "de 2005 - 2010 environ"),
        ("non‑profit", "a non-profit body"),
        ("co­operative", "a cooperative body"),
    ],
)
def test_quotes_apostrophes_dashes_and_invisible_characters_are_normalised(
    quote: str, text: str
) -> None:
    assert found(quote, text)


def test_accented_text_matches_in_either_unicode_form() -> None:
    composed = "Société Générale fondée à Zürich, ça marche"
    decomposed = "Société Générale fondée à Zürich, ça marche"
    assert found(composed, decomposed)
    assert found(decomposed, composed)


def test_accents_are_not_dropped_for_a_quote() -> None:
    assert not found("Societe Generale", "Société Générale")


def test_cjk_text_is_matched_with_full_width_forms_normalised() -> None:
    text = "株式会社アクメは１９８５年に東京で設立されました。従業員数は２５０名です。"
    assert found("1985年に東京で設立", text)  # full-width digits fold to ASCII (NFKC)
    assert found("従業員数は250名です", text)
    assert found("株式会社アクメ", text)
    assert not found("株式会社アクミ", text)


def test_a_cjk_quote_split_by_a_line_break_is_found() -> None:
    assert found("总部位于上海", "公司总部位于\n上海市浦东新区。".replace("\n", ""))
    assert found("上海 浦东", "上海\n浦东")


def test_case_is_not_ignored() -> None:
    assert not found("ISO 9001", "iso 9001")


def test_the_redaction_mark_is_matched_against_the_stored_text() -> None:
    stored = "Managing director: […], appointed in 2019."
    assert found("Managing director: […], appointed", stored)
    assert not found("Managing director: Anna Keller, appointed", stored)
    assert is_redacted_quote("Managing director: […], appointed")
    assert is_redacted_quote("Managing director: [...], appointed")
    assert not is_redacted_quote("Managing director appointed")


def test_the_quote_limit_is_300_characters() -> None:
    assert MAX_QUOTE_CHARS == 300


@pytest.mark.parametrize(
    ("value", "quote"),
    [
        ("250", "employs 250 people at its plant in Lyon"),
        ("1200000", "capital of 1 200 000 euros"),
        ("1 200 000", "capital of 1.200.000 euros"),
        ("1.200.000", "capital of 1200000 euros"),
        ("1,2", "growth of 1.2 percent"),
        ("1.2", "croissance de 1,2 pour cent"),
        ("2005-03-14", "Founded on 14 March 2005"),
        ("2005-03", "Gegründet im März 2005"),
        ("Yes", "We hold ISO 9001 certification"),  # words are not checked
        ("Germany", "Headquarters in Stuttgart"),
        ("CEO", "Directeur général"),
        ("Lyon, France", "employs 250 people at its plant in Lyon"),
    ],
)
def test_a_legitimate_value_is_supported(value: str, quote: str) -> None:
    assert value_supported(value, quote)


@pytest.mark.parametrize(
    ("value", "quote"),
    [
        ("2020", "Founded in 1998"),
        ("1066", "Founded in 1998"),
        ("2006-03-14", "Founded on 14 March 2005"),
        ("1200001", "capital of 1 200 000 euros"),
        ("  ", "some quote of text"),
    ],
)
def test_an_invented_figure_or_an_empty_value_is_not_supported(value: str, quote: str) -> None:
    assert not value_supported(value, quote)


@pytest.mark.parametrize(
    ("quote", "minimum", "minimum_cjk", "expected"),
    [
        ("x" * 12, 12, 4, True),
        ("x" * 11, 12, 4, False),
        ("5", 12, 4, False),
        ("  room   number 5  ", 12, 4, True),  # counted after normalisation: 13 characters
        ("a  b  c  d  e  f ", 12, 4, False),  # 11 once the spaces are reduced
        ("東京本社", 12, 4, True),
        ("東京本", 12, 4, False),
        ("서울 본사", 12, 4, True),
        ("カタカナ", 12, 4, True),
        ("ひらがな", 12, 4, True),
        ("Tokyo 本社", 12, 4, True),  # has CJK: the limit of 4 applies
    ],
)
def test_a_quote_must_carry_evidence(
    quote: str, minimum: int, minimum_cjk: int, expected: bool
) -> None:
    assert quote_long_enough(quote, minimum, minimum_cjk) is expected


def test_chunks_cover_the_text_within_the_size() -> None:
    text = ("word " * 50 + "\n") * 10
    pieces = list(chunks(text, 120))

    assert "".join(pieces) == text
    assert all(len(piece) <= 120 for piece in pieces)
    assert len(pieces) > 1


def test_chunks_cut_cjk_text_where_the_size_ends() -> None:
    text = "東京" * 100
    pieces = list(chunks(text, 60))

    assert "".join(pieces) == text and all(len(p) <= 60 for p in pieces)


def test_a_short_text_is_one_chunk() -> None:
    assert list(chunks("short", 100)) == ["short"]
    assert list(chunks("", 100)) == []

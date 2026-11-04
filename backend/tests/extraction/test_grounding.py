"""The grounding check (#23): quote found after normalisation, accented and CJK text, length,
the redaction mark, and the support of the value by its quote. No database."""

import pytest

from app.extraction.grounding import (
    MAX_QUOTE_CHARS,
    fold,
    is_redacted_quote,
    normalise,
    quote_in_text,
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


def test_a_value_supported_by_its_quote() -> None:
    text = fold("The company employs 250 people at its plant in Lyon (France).")
    quote = "employs 250 people at its plant in Lyon"
    assert value_supported("250", quote, text)
    assert value_supported("Lyon, France", quote, text)
    assert value_supported("250 employees", quote, fold("250 employees " + text))


def test_a_number_that_is_not_in_the_quote_is_not_supported() -> None:
    text = fold("Founded in 1998. In 2020 the company had 250 employees.")
    assert not value_supported("2020", "Founded in 1998", text)  # in the source, not the quote
    assert not value_supported("1066", "Founded in 1998", text)


def test_a_word_that_is_not_in_the_source_is_not_supported() -> None:
    text = fold("Acme is a family business based in Lyon.")
    assert not value_supported("Zorgon Holdings", "a family business based in Lyon", text)


def test_support_ignores_case_and_accents_and_works_for_cjk() -> None:
    text = fold("Société anonyme au capital de 1 000 000 euros")
    assert value_supported("SOCIETE ANONYME", "Société anonyme", text)
    cjk = fold("本社は東京にあります。")
    assert value_supported("東京", "本社は東京にあります", cjk)
    assert not value_supported("大阪", "本社は東京にあります", cjk)


def test_a_value_with_nothing_to_check_is_not_supported() -> None:
    assert not value_supported("--", "quote", fold("text"))


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

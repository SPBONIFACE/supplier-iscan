"""#219: a phone number is redacted wherever it stands, however many numeric lines come before it.

Fast tests: fixed-seed synthetic tables, a fake name detector, both passes (`redact` and
`redact_stored`).
"""

import re
from collections.abc import Callable

import pytest

from app.models import Source
from app.redaction import StoredSourceText
from app.redaction.engine import _phone_spans
from tests.redaction.phone_table import PHONE, old_phone_spans, one_line, prose, table
from tests.redaction.support import fake_redactor

MARK = "[…]"


def full_pass(text: str) -> str:
    return fake_redactor().redact(text).text


def fast_pass(text: str) -> str:
    return fake_redactor().redact_stored(StoredSourceText.of(Source(redacted_text=text))).text


PASSES = pytest.mark.parametrize("run", [full_pass, fast_pass], ids=["redact", "redact_stored"])


@PASSES
@pytest.mark.parametrize("rows", [300, 1000, 5000])
def test_a_phone_after_many_numeric_rows_is_redacted(run: Callable[[str], str], rows: int) -> None:
    out = run(f"{table(rows)}\nContact {PHONE}.")
    assert "555 01 23" not in out and f"Contact {MARK}." in out


@PASSES
def test_a_phone_after_5000_figures_on_one_line_is_redacted(run: Callable[[str], str]) -> None:
    out = run(f"{one_line(5000)} contact {PHONE}.")
    assert "555 01 23" not in out and f"contact {MARK}." in out


@PASSES
@pytest.mark.parametrize(
    "phone",
    [
        "+41 79 555 01 23",
        "+33 1.23.45.67.89",
        "+49 (0)89 636-00",
        "01 42 68 53 00",
        "030 123456",
        "+1 415 555 2671",
    ],
)
def test_every_format_is_redacted_after_1000_rows(run: Callable[[str], str], phone: str) -> None:
    out = run(f"{table(1000)}\nCall {phone}.")
    assert out.endswith(f"Call {MARK}."), out[-60:]


@PASSES
def test_a_number_on_the_last_line_without_a_newline_is_redacted(run: Callable[[str], str]) -> None:
    out = run(f"{table(1000)}\n{PHONE}")
    assert out.endswith(f"\n{MARK}")


def test_the_synthetic_tables_give_no_span() -> None:
    assert _phone_spans(table(300)) == []
    assert _phone_spans(table(5000)) == []
    assert _phone_spans(one_line(5000)) == []


QA_LISTS = [
    "01 42 68 53 00,01 42 68 53 01",
    "Tel 0142685300,0142685301",
    "Fax: 030 123456,2 copies",
    "1.01 42 68 53 00",
    "0142685300,0142685301,0142685302",
    "Tel 01 42 68 53 00,01 42 68 53 01,01 42 68 53 02",
    "1,01 42 68 53 00,2",
    "x 12,030 123456,4 y",
    "Tel 2.0142685300.5",
    "1.01 42 68 53 00.2",
    "076 123 45 67,076 123 45 68,076 123 45 69",
]

SMALL_TEXTS = [
    f"Tel {PHONE} or +33 1.23.45.67.89 or +49 (0)89 636-00.",
    "Appel 01 42 68 53 00, Büro 030 123456, US +1 415 555 2671, UK 020 7946 0958.",
    "SIREN 552 100 554, LEI 5493001KJTIIGC8Y1R12, VAT FR40 303 265 045, revenue 12 345 678,90.",
    "ID 123e4567-e89b-12d3-a456-426614174000 then 0123456789 and 2024-11-27 12:30:45.",
    "Ligne 1\n+34 912 345 678\nLigne 3 +39 06 1234 5678\n(0)89 636-00\n030-123456\n",
    "Broken across\n+41 79 555\n01 23 and nothing else, 1 2 3 4 5 6 7 8 9 10.",
    "Fax 0044 20 7946 0958; mobile +44 7911 123456; whatsapp 06 12 34 56 78.",
    *QA_LISTS,
    table(12),
    f"{table(8)}\nTel {PHONE}\n{table(8, seed=5)}",
    prose(8000, True),
    "",
]


@pytest.mark.parametrize("text", SMALL_TEXTS)
def test_on_texts_within_the_old_budget_the_spans_are_those_of_main(text: str) -> None:
    assert sorted(_phone_spans(text)) == sorted(old_phone_spans(text))


def test_the_differential_texts_really_fit_the_old_budget() -> None:
    # The old rule found numbers in these texts, so the comparison is not empty.
    assert sum(len(old_phone_spans(text)) for text in SMALL_TEXTS) >= 12


def test_the_corpus_table_spans_are_figure_slices_and_nothing_else() -> None:
    """Trade-off (owner rule: privacy over figures): the full scan hides a few slices of figures
    such as `016 88` in "26.016 88.461" in the 400-row corpus table. Pinned so a change shows."""
    from tests.redaction.perf_corpus import numeric_table

    text = numeric_table()
    spans = {text[a:b] for a, b in _phone_spans(text)}
    assert spans == {"016 88", "016 43", "076 497 37", "016 93"}


@PASSES
def test_a_phone_after_the_corpus_table_is_redacted(run: Callable[[str], str]) -> None:
    from tests.redaction.perf_corpus import numeric_table

    out = run(f"{numeric_table()}\nCall {PHONE}, or 01 42 68 53 00.")
    assert out.endswith(f"Call {MARK}, or {MARK}.")


@PASSES
@pytest.mark.parametrize("text", QA_LISTS)
def test_phone_lists_without_a_space_after_the_comma_are_redacted(
    run: Callable[[str], str], text: str
) -> None:
    out = run(text)
    assert not re.search(r"\d{3}|\d\d \d\d", out), out

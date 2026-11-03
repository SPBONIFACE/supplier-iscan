"""The real name-detection model (#19): needs `make fetch-model`; run by `make test-model` and CI.

Figures come from the synthetic evaluation set (`evalset/`, see its README); the full report is
`python -m tests.redaction.measure_detector`. These tests keep the thresholds of the targets.
"""

import os
from collections import defaultdict

import pytest

from app.redaction import OMISSION, Redactor, RedactionContext
from tests.redaction.measure_detector import covered, load, touched

pytestmark = pytest.mark.model
LATIN = ("en", "fr", "de", "es", "it")


@pytest.fixture(scope="module")
def redactor(real_redactor: Redactor) -> Redactor:
    return real_redactor


def test_the_model_runs_offline_and_without_remote_code(redactor: Redactor) -> None:
    redactor.load()

    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_the_checkpoint_is_loaded_with_weights_only(real_redactor: Redactor) -> None:
    import torch

    from app.redaction.detector import _pickle_safe_load

    original = torch.load
    with _pickle_safe_load():
        assert torch.load is not original
        with pytest.raises(Exception, match="redaction is unavailable"):
            torch.load("unused", weights_only=False)
    assert torch.load is original


@pytest.mark.parametrize(
    ("text", "gone", "kept"),
    [
        ("Kind regards,\nHollis Varney\nSales Office", "Varney", "Sales Office"),
        ("Contact: JEAN DUPONT, Purchasing Director", "DUPONT", "Purchasing Director"),
        ("Mit freundlichen Grüßen\nDietmar Kaltenbach\nVertrieb", "Kaltenbach", "Vertrieb"),
        ("mr smith called, mail jean@acme.com", "jean@acme.com", "called"),
        ("联系人：王浩然，销售部", "浩然", "销售部"),
    ],
)
def test_a_name_goes_and_what_surrounds_it_stays(
    redactor: Redactor, text: str, gone: str, kept: str
) -> None:
    out = redactor.redact(text).text

    assert gone not in out and kept in out and OMISSION in out


def test_a_chinese_name_in_a_text_with_other_languages_is_removed(redactor: Redactor) -> None:
    out = redactor.redact("Contact: Anna Meyer\n联系人：陈雨桐").text

    assert "Meyer" not in out and "雨桐" not in out


def test_a_name_on_a_chunk_boundary_is_removed(redactor: Redactor) -> None:
    filler = "The delivery schedule is confirmed for the next quarter. " * 40
    for shift in (0, 7, 31, 100):
        text = filler[: 1_200 - shift] + "Hollis Varney spoke. " + filler
        assert "Varney" not in redactor.redact(text).text, shift


def test_a_company_with_a_legal_form_survives(redactor: Redactor) -> None:
    text = "Kaltenbach & Söhne Maschinenbau GmbH & Co. KG supplies the plant."

    assert redactor.redact(text).text == text


def test_a_registry_company_name_is_protected(redactor: Redactor) -> None:
    text = "Brightwater Anders delivered the parts."

    out = redactor.redact(text, RedactionContext(keep=("Brightwater Anders",))).text

    assert out == text


def test_recall_on_the_fresh_set_meets_the_targets(redactor: Redactor) -> None:
    cells: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for item in load("fresh", "names"):
        removed = redactor.removed_spans(item["text"])
        for start, end in item["spans"]:
            cell = cells[(item["lang"], item["style"])]
            cell[0] += covered(item["text"], start, end, removed)
            cell[1] += 1
    for style, target in (("normal", 0.98), ("all_caps", 0.95), ("lower", 0.95)):
        for lang in LATIN:
            ok, total = cells[(lang, style)]
            assert ok / total >= target, (lang, style, ok, total)


def test_ordinary_lines_are_left_alone_and_titles_stay(redactor: Redactor) -> None:
    ordinary = [i for i in load("main", "ordinary") if i["id"] % 10 >= 3]
    altered = [i["text"] for i in ordinary if redactor.removed_spans(i["text"])]
    assert len(altered) / len(ordinary) <= 0.03, altered

    titles = [i for i in load("main", "titles") if i["id"] % 10 >= 3]
    good = 0
    for item in titles:
        removed = redactor.removed_spans(item["text"])
        good += covered(item["text"], *item["name_span"], removed) and not touched(
            item["text"], *item["title_span"], removed
        )
    assert good >= len(titles) - 1

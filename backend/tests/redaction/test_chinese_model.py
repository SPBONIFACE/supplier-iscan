"""Chinese names with the real models (#100): needs `make fetch-model`; run by `make test-model`.

The thresholds are checked on the tuning part of `evalset/zh/` (the report part is only run by
`python -m tests.redaction.measure_detector --zh report`, once, and never used to choose a rule).
"""

import pytest

from app.redaction import Redactor
from tests.redaction.measure_detector import covered, load, touched

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def redactor(real_redactor: Redactor) -> Redactor:
    return real_redactor


def _tuning(name: str) -> list[dict]:  # type: ignore[type-arg]
    return [item for item in load("zh", name) if item["id"] % 10 < 3]


def test_chinese_names_are_hidden_on_the_tuning_part(redactor: Redactor) -> None:
    hidden: dict[str, list[int]] = {"han": [0, 0], "latin": [0, 0]}
    for item in _tuning("names"):
        removed = redactor.removed_spans(item["text"])
        for (start, end), script in zip(item["spans"], item["scripts"], strict=True):
            hidden[script][0] += covered(item["text"], start, end, removed)
            hidden[script][1] += 1

    for script, (ok, total) in hidden.items():
        assert ok / total >= 0.95, (script, ok, total)


def test_titles_next_to_chinese_names_stay_readable(redactor: Redactor) -> None:
    items = [item for item in _tuning("names") if item["title_spans"]]
    good = 0
    for item in items:
        removed = redactor.removed_spans(item["text"])
        text = item["text"]
        good += all(covered(text, a, b, removed) for a, b in item["spans"]) and not any(
            touched(text, a, b, removed) for a, b in item["title_spans"]
        )

    assert good / len(items) >= 0.95, (good, len(items))


def test_the_invented_suzhou_company_is_never_altered(redactor: Redactor) -> None:
    cases = [item for item in load("zh", "nonperson") if item["suzhou"]]
    assert len(cases) >= 12
    for item in cases:
        assert not redactor.removed_spans(item["text"]), item["text"]


def test_chinese_companies_places_and_products_are_rarely_altered(redactor: Redactor) -> None:
    altered = total = 0
    for item in _tuning("nonperson"):
        removed = redactor.removed_spans(item["text"])
        for start, end in item["items"]:
            altered += touched(item["text"], start, end, removed)
            total += 1

    assert altered / total <= 0.06, (altered, total)


@pytest.mark.parametrize(
    "text",
    [
        "BERICAP China and Suzhou Zi Jin Plastic Co., Ltd wrote a success story without compare",
        "苏州紫金塑料有限公司",
        "我们的供应商苏州紫金塑料有限公司位于苏州。",
    ],
)
def test_a_chinese_company_stays_whole(redactor: Redactor, text: str) -> None:
    assert redactor.redact(text).text == text


def test_the_same_name_in_han_and_romanised_form_goes_twice(redactor: Redactor) -> None:
    out = redactor.redact("王浩然 (Wang Haoran) is our contact for the Suzhou plant.").text

    assert "王浩然" not in out and "Wang" not in out and "Haoran" not in out
    assert "Suzhou plant" in out


def test_a_name_at_the_start_and_the_end_of_a_chunk_is_hidden(redactor: Redactor) -> None:
    body = "我们的产品系列包括各种塑料瓶盖和包装材料，交货期为四周。" * 20
    text = "陈雨桐" + body + "\n负责人：王浩然\n" + body + "刘子墨"
    assert len(text) > 2 * 400

    out = redactor.redact(text).text

    for name in ("陈雨桐", "王浩然", "刘子墨"):
        assert name not in out, name

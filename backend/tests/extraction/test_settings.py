"""Extraction settings (#23): the input size and the IAF CertSearch link."""

import pytest

from app.config import ConfigurationError
from app.extraction.settings import DEFAULT_CERTSEARCH_URL, load_extraction_settings


def test_defaults() -> None:
    settings = load_extraction_settings({})

    assert settings.max_input_chars == 20_000
    assert settings.certsearch_url == DEFAULT_CERTSEARCH_URL


def test_values_from_the_environment() -> None:
    settings = load_extraction_settings(
        {"EXTRACT_MAX_INPUT_CHARS": "5000", "IAF_CERTSEARCH_URL": "https://certsearch.example/x"}
    )

    assert (settings.max_input_chars, settings.certsearch_url) == (
        5000,
        "https://certsearch.example/x",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EXTRACT_MAX_INPUT_CHARS", "ten"),
        ("EXTRACT_MAX_INPUT_CHARS", "42"),
        ("IAF_CERTSEARCH_URL", "javascript:alert(1)"),
        ("IAF_CERTSEARCH_URL", "ftp://certsearch.example"),
        ("IAF_CERTSEARCH_URL", "https://user:pw@certsearch.example"),
    ],
)
def test_a_bad_value_is_refused_naming_the_setting_not_the_value(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        load_extraction_settings({name: value})

    assert name in str(caught.value) and value not in str(caught.value)

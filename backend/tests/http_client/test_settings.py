"""The timeout and redirect maximum are configured through the environment."""

import pytest

from app.config import ConfigurationError
from app.http_client import FetchSettings, load_fetch_settings


def test_defaults_apply_when_nothing_is_set() -> None:
    assert load_fetch_settings({}) == FetchSettings(
        timeout_seconds=10.0, max_redirects=5, website_check_timeout_seconds=10.0
    )


def test_values_come_from_the_environment() -> None:
    settings = load_fetch_settings(
        {
            "FETCH_TIMEOUT_SECONDS": "20",
            "FETCH_MAX_REDIRECTS": "0",
            "WEBSITE_CHECK_TIMEOUT_SECONDS": "2.5",
        }
    )

    assert settings == FetchSettings(
        timeout_seconds=20.0, max_redirects=0, website_check_timeout_seconds=2.5
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FETCH_TIMEOUT_SECONDS", "ten"),
        ("FETCH_TIMEOUT_SECONDS", "0"),
        ("FETCH_TIMEOUT_SECONDS", "-1"),
        ("FETCH_TIMEOUT_SECONDS", "301"),
        ("WEBSITE_CHECK_TIMEOUT_SECONDS", "nan"),
        ("FETCH_MAX_REDIRECTS", "2.5"),
        ("FETCH_MAX_REDIRECTS", "-1"),
        ("FETCH_MAX_REDIRECTS", "21"),
    ],
)
def test_unacceptable_values_stop_startup_with_a_named_error(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError, match=name):
        load_fetch_settings({name: value})

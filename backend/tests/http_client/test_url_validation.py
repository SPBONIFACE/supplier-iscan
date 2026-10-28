"""Criteria 3 and 4: only http(s), clear validation errors, internationalised domain names."""

import pytest

from app.http_client import InvalidUrlError, normalise_url
from app.http_client.url_guard import (
    MSG_CREDENTIALS,
    MSG_EMPTY,
    MSG_HOST,
    MSG_MALFORMED,
    MSG_PORT,
    MSG_SCHEME,
)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", MSG_EMPTY),
        ("   ", MSG_EMPTY),
        ("http://", MSG_HOST),
        ("https:///path-only", MSG_HOST),
        ("http://exa mple.com", MSG_MALFORMED),
        ("http://example.com/\x00", MSG_MALFORMED),
        ("http://-bad-.com", MSG_HOST),
        ("http://exa%41mple.com", MSG_HOST),
        ("http://under_score.com", MSG_HOST),
        ("http://" + "a" * 64 + ".com", MSG_HOST),
        ("http://example.com:99999/", MSG_PORT),
        ("http://example.com:0/", MSG_PORT),
        ("file:///etc/passwd", MSG_SCHEME),
        ("ftp://example.com/file", MSG_SCHEME),
        ("javascript:alert(1)", MSG_SCHEME),
        ("JavaScript:alert(1)", MSG_SCHEME),
        ("mailto:sales@example.com", MSG_SCHEME),
        ("data:text/html,hello", MSG_SCHEME),
        ("gopher://example.com/", MSG_SCHEME),
        ("http://user:secret@example.com/", MSG_CREDENTIALS),
        ("https://user@example.com/", MSG_CREDENTIALS),
        ("https://:secret@example.com/", MSG_CREDENTIALS),
        ("http://@example.com/", MSG_CREDENTIALS),  # empty user name (QA minor point on #15)
        ("https://@example.com", MSG_CREDENTIALS),
    ],
)
def test_invalid_input_returns_a_validation_error_with_a_clear_message(
    raw: str, message: str
) -> None:
    with pytest.raises(InvalidUrlError) as raised:
        normalise_url(raw, assume_https=True)

    assert raised.value.reason == message
    assert raised.value.code == "invalid_url"
    assert isinstance(raised.value, ValueError)


def test_a_bare_domain_is_refused_unless_https_may_be_assumed() -> None:
    with pytest.raises(InvalidUrlError):
        normalise_url("example.com")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "https://example.com/"),
        ("  Example.COM/about  ", "https://example.com/about"),
        ("example.com:8443/x?y=1", "https://example.com:8443/x?y=1"),
        ("http://example.com", "http://example.com/"),
        ("https://example.com?q=1#top", "https://example.com/?q=1#top"),
        ("HTTPS://www.example.com/", "https://www.example.com/"),
        ("https://example.com./", "https://example.com/"),
        ("https://93.184.215.14/", "https://93.184.215.14/"),
        ("https://[2606:2800::1]:8443/", "https://[2606:2800::1]:8443/"),
    ],
)
def test_valid_input_is_normalised(raw: str, expected: str) -> None:
    assert str(normalise_url(raw, assume_https=True)) == expected


@pytest.mark.parametrize(
    ("raw", "punycode"),
    [
        ("münchen.de", "xn--mnchen-3ya.de"),
        ("https://MÜNCHEN.de/über-uns", "xn--mnchen-3ya.de"),
        ("https://xn--mnchen-3ya.de", "xn--mnchen-3ya.de"),
        ("https://société.fr", "xn--socit-esab.fr"),
        ("北京大学.cn", "xn--1lq90ic7fzpc.cn"),
    ],
)
def test_internationalised_domain_names_are_accepted_and_converted_to_punycode(
    raw: str, punycode: str
) -> None:
    url = normalise_url(raw, assume_https=True)

    assert url.raw_host.decode("ascii") == punycode
    assert url.scheme == "https"

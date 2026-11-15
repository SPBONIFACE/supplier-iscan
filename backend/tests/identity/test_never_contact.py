"""#186: a candidate website on a domain whose terms forbid automated collection is not fetched."""

import pytest

from app.identity.agent import _guarded_website_check


class _NoRequest:
    """A client that fails the test when it is used."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the website was requested ({name})")


@pytest.mark.parametrize(
    "raw", ["https://www.linkedin.com/company/acme", "fr.linkedin.com/company/acme", "linkedin.com"]
)
def test_a_never_contact_website_is_not_fetched(raw: str) -> None:
    result = _guarded_website_check(raw, _NoRequest())

    assert result.status == "unreachable"
    assert result.failure == "not_contacted"
    assert "not contacted" in (result.reason or "")

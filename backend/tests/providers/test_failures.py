class _Answer:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


class _Limited(Exception):
    def __init__(self, headers: dict[str, str] | None) -> None:
        self.response = _Answer(headers) if headers is not None else None


def test_retry_after_is_read_in_seconds_and_capped() -> None:
    from app.providers.failures import MAX_RETRY_AFTER, retry_after_seconds

    assert retry_after_seconds(_Limited({"retry-after": "7"})) == 7.0
    assert retry_after_seconds(_Limited({"retry-after": "3600"})) == MAX_RETRY_AFTER
    assert retry_after_seconds(_Limited({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None
    assert retry_after_seconds(_Limited({"retry-after": "-3"})) is None
    assert retry_after_seconds(_Limited({"retry-after": "nan"})) is None
    assert retry_after_seconds(_Limited({})) is None
    assert retry_after_seconds(_Limited(None)) is None
    assert retry_after_seconds(ValueError("no response")) is None

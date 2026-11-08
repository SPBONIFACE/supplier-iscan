"""The type that carries text through the redaction gate (#19).

`RedactedText` can be created only by the redaction module (`mint`, private to the package). The
provider interface accepts nothing else: a raw `str` is refused at run time, not only by the type
checker. `repr` hides the text: it is never logged.
"""

from typing import Final

OMISSION: Final = "[…]"


class RedactionUnavailable(Exception):
    """Redaction could not run (model not loaded, text too long, internal failure).

    The message is fixed and plain: it never carries the text, nor a fragment of it. Callers send
    nothing to a provider and store nothing; there is no fallback to unredacted text.
    """

    REASON: Final = (
        "Personal-data redaction is unavailable, so nothing was sent to an AI provider "
        "or stored. Try again later."
    )

    def __init__(self) -> None:
        super().__init__(self.REASON)


_MINT: Final = object()


class RedactedText:
    """Text that has passed the redaction gate."""

    _chars: str

    def __init__(self, text: str, *, _token: object = None) -> None:
        if _token is not _MINT or not isinstance(text, str):
            raise TypeError("RedactedText can only be created by the redaction module")
        object.__setattr__(self, "_chars", text)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("RedactedText is immutable")

    @property
    def text(self) -> str:
        return self._chars

    def __len__(self) -> int:
        return len(self._chars)

    def __repr__(self) -> str:
        return f"RedactedText(<{len(self._chars)} characters>)"

    __str__ = __repr__


def mint(text: str) -> RedactedText:
    """Package-private: called only by the engine, after redacting."""
    return RedactedText(text, _token=_MINT)

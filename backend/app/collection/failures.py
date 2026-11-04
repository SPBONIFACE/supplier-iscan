"""The failure log of collection (spec F2): what failed, which strategy was tried, what is next.

The strategy ladder is website (home page and its links), then sitemap, then retrieval (the
retrieval provider). A failure names the strategy in force and the next one; after retrieval there
is none, and the run continues with the sources it has. Messages are plain language and never make
a claim about the supplier (skill `evidence-wording`): a page that gave nothing is "No public
evidence found" from that page, not a statement about the supplier.
"""

from dataclasses import dataclass
from typing import Final, Literal

Strategy = Literal["website", "sitemap", "retrieval"]
Kind = Literal[
    "http_error",
    "timeout",
    "unreachable",
    "empty_content",
    "blocked_by_robots",
    "refused",
    "too_large",
    "not_a_page",
    "provider_unavailable",
    "invalid_response",
    "attempt_cap",
]

NEXT_STRATEGY: Final[dict[Strategy, Strategy | None]] = {
    "website": "sitemap",
    "sitemap": "retrieval",
    "retrieval": None,
}

MESSAGES: Final[dict[Kind, str]] = {
    "http_error": "The page answered with an error and could not be read.",
    "timeout": "The page did not answer in time.",
    "unreachable": "The page could not be reached.",
    "empty_content": "No public evidence found: the page had no readable text.",
    "blocked_by_robots": (
        "The site does not allow automated reading of this page (robots.txt or a reservation "
        "of the site owner), so it was not collected."
    ),
    "refused": "The address is not a public web address and was not fetched.",
    "too_large": "The file is larger than the allowed size and was not read.",
    "not_a_page": "The address is not a web page or a PDF report and was not read.",
    "provider_unavailable": (
        "The retrieval provider is unavailable, so no additional sources were searched."
    ),
    "invalid_response": "The retrieval provider's answer could not be used.",
    "attempt_cap": "The limit of attempts for this run was reached; the rest were not tried.",
}


@dataclass(frozen=True)
class Failure:
    url: str | None
    strategy: Strategy
    kind: Kind
    next_strategy: Strategy | None
    message: str


# The ceilings of #103 use the contract's `attempt_cap` kind with their own plain message.
REQUEST_CAP_MESSAGE: Final = (
    "The limit of requests for this run was reached; the run went on with what it had."
)
DOMAIN_CAP_MESSAGE: Final = (
    "The limit of websites contacted for this run was reached; this address was not requested."
)


def make_failure(
    url: str | None,
    strategy: Strategy,
    kind: Kind,
    status: int | None = None,
    message: str | None = None,
) -> Failure:
    message = message or MESSAGES[kind]
    if message == MESSAGES[kind] and kind == "http_error" and status is not None:
        message = f"The page answered with an error ({status}) and could not be read."
    return Failure(url, strategy, kind, NEXT_STRATEGY[strategy], message)


class RetrievalFailed(Exception):
    """The retrieval step could not get addresses; the run goes on with its other sources."""

    def __init__(self, kind: Kind) -> None:
        super().__init__(kind)
        self.kind = kind

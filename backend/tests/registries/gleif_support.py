"""A scripted GLEIF API for the group tests (#142): synthetic records in the real answer shape.

Nothing here reaches the network: ``FakeGleif`` is the ``Fetch`` the polite client calls.
"""

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from app.registries.http import FetchedResponse, FetchError

PREFIX = "/api/v1/lei-records/"
CHILD_LEI = "5299000CHILD0000001"
PARENT_LEI = "5299000PARENT000000A"
SUB_LEI = "5299000SUB00000000FR"


def lei_record(
    lei: str,
    name: str,
    city: str = "Paris",
    country: str = "FR",
    status: str = "ACTIVE",
    form: str | None = "SAS",
    registered_as: str | None = "552 081 317",
) -> dict[str, Any]:
    address = {
        "addressLines": ["1 Rue de la Paix"],
        "postalCode": "75002",
        "city": city,
        "country": country,
    }
    return {
        "type": "lei-records",
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {
                "legalName": {"name": name},
                "legalForm": {"id": "8888", "other": form},
                "legalAddress": address,
                "headquartersAddress": {**address, "addressLines": ["2 Avenue Foch"]},
                "registeredAs": registered_as,
                "status": status,
            },
        },
    }


class FakeGleif:
    """Answers by path below ``/api/v1/lei-records/``; a path with no answer is a 404.

    A value that is an exception is raised (``FetchError("timeout")``); an int is a bare status.
    """

    def __init__(self, answers: Mapping[str, Any]) -> None:
        self.answers = dict(answers)
        self.paths: list[str] = []

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> FetchedResponse:
        path = urlsplit(url).path.removeprefix(PREFIX)
        self.paths.append(path)
        answer = self.answers.get(path)
        if isinstance(answer, FetchError):
            raise answer
        if isinstance(answer, int):
            return FetchedResponse(answer, b"{}")
        if answer is None:
            return FetchedResponse(404, b'{"errors": [{"status": "404"}]}')
        return FetchedResponse(200, json.dumps(answer).encode())


def one(record: dict[str, Any]) -> dict[str, Any]:
    return {"data": record}


def many(*records: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {
        "meta": {"pagination": {"total": total if total is not None else len(records)}},
        "data": list(records),
    }


def group_answers() -> dict[str, Any]:
    """A French subsidiary whose ultimate parent is a German holding with three more entities."""
    return {
        SUB_LEI: one(lei_record(SUB_LEI, "Acme France SAS")),
        f"{SUB_LEI}/direct-parent": one(
            lei_record(CHILD_LEI, "Acme Europe BV", "Amsterdam", "NL", form="BV")
        ),
        f"{SUB_LEI}/ultimate-parent": one(
            lei_record(PARENT_LEI, "Acme Holding GmbH", "Munich", "DE", form="GmbH")
        ),
        f"{PARENT_LEI}/ultimate-children": many(
            lei_record(SUB_LEI, "Acme France SAS"),
            lei_record(CHILD_LEI, "Acme Europe BV", "Amsterdam", "NL", form="BV"),
            lei_record("5299000DEAD00000000X", "Acme Old SAS", status="INACTIVE"),
            total=3,
        ),
    }

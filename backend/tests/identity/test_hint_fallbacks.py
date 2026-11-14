"""The buyer's country and website hints when the registries offer no fitting candidate.

A candidate that contradicts the country hint is not proposed while another one fits; the website
the buyer gave becomes a candidate (once checked) when no registry candidate fits. Nothing is
discarded: every registry candidate stays under "Show other candidates".
"""

from typing import Any

import httpx2
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SupplierIdentity
from app.providers import RetrievedUrl
from tests.identity.support import WEBSITE_HOST, candidate, found, proposal
from tests.identity.test_identity import ACME, ACME_ID, OTHER, OTHER_ID, setup

SWISS = candidate(
    "Acme Closures AG",
    legal_name="Acme Closures AG",
    country="CH",
    country_name="Switzerland",
    lei="5299SWISS000000000AA",
    wikidata_id="Q3",
)
SWISS_ID = "lei:5299SWISS000000000AA"
WEB_ID = f"web:{WEBSITE_HOST}"


def _others(member: Any, session: dict[str, Any]) -> list[str]:
    listed = member.call("GET", f"/identity-sessions/{session['id']}/candidates").json()
    return [c["id"] for c in listed["candidates"]]


def test_a_candidate_in_the_wrong_country_gives_way_to_one_in_the_right_country(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found(ACME, SWISS), model=[proposal(ACME_ID)])

    session = member.open(hints={"country": "CH"})

    last = session["turns"][-1]
    assert last["kind"] == "proposal" and last["candidate"]["id"] == SWISS_ID
    assert _others(member, session) == [ACME_ID]  # not discarded


def test_the_website_hint_is_proposed_when_no_candidate_is_in_the_buyers_country(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found(ACME), model=[proposal(ACME_ID)])

    session = member.open(hints={"country": "CH", "website": f"https://{WEBSITE_HOST}"})

    last = session["turns"][-1]
    assert last["kind"] == "proposal" and last["candidate"]["id"] == WEB_ID
    assert last["text"].startswith("I found no company with this name in Switzerland")
    assert ACME_ID in _others(member, session)
    assert session["hints"] == {
        "website": f"https://{WEBSITE_HOST}/",
        "country": "CH",
        "sector": None,
    }


def test_the_website_hint_is_proposed_when_the_registries_find_nothing(
    engine: Engine, settings: Settings
) -> None:
    harness, member = setup(engine, settings, found())

    session = member.open(hints={"website": WEBSITE_HOST})

    last = session["turns"][-1]
    assert last["kind"] == "proposal" and last["candidate"]["id"] == WEB_ID
    assert last["candidate"]["found_in"] == ["website"]
    assert harness.model.calls == []  # code proposes it, not the model

    confirmed = member.call(
        "POST", f"/identity-sessions/{session['id']}/confirm", json={"candidate_id": WEB_ID}
    )
    assert confirmed.status_code == 200


def test_without_a_fitting_candidate_or_website_no_wrong_country_card_is_shown(
    engine: Engine, settings: Settings
) -> None:
    """The website field opens with the reason; the closest candidate is named, not proposed."""
    harness, member = setup(engine, settings, found(ACME), model=[proposal(ACME_ID)])

    session = member.open(hints={"country": "CH"}, ui_language="fr")

    last = session["turns"][-1]
    assert last["kind"] == "website_rejected" and last["candidate"] is None
    assert "(Suisse)" in last["text"] and "France" in last["text"]
    assert "Acme Supplies SA" in last["text"]
    assert len(harness.web.calls) == 1  # the web search was tried (unscripted here: it failed)
    assert ACME_ID in _others(member, session)  # not discarded


def test_stating_the_closest_candidates_country_in_the_chat_proposes_it(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(
        engine,
        settings,
        found(ACME),
        model=[proposal(ACME_ID), proposal(ACME_ID, country_hint="fr")],
    )
    session = member.open(hints={"country": "CH"})

    after = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/messages",
        json={"text": "Yes, the French one."},
    ).json()

    last = after["turns"][-1]
    assert last["kind"] == "proposal" and last["candidate"]["id"] == ACME_ID


def test_an_unreachable_website_hint_is_said_once_and_the_candidates_stay(
    engine: Engine, settings: Settings
) -> None:
    pages = {(WEBSITE_HOST, "/"): httpx2.Response(503)}
    _harness, member = setup(
        engine, settings, found(OTHER), model=[proposal(OTHER_ID), proposal(OTHER_ID)], pages=pages
    )

    session = member.open(hints={"country": "CH", "website": WEBSITE_HOST})
    after = member.call(
        "POST", f"/identity-sessions/{session['id']}/messages", json={"text": "Not this one."}
    ).json()

    notices = [t for t in after["turns"] if t["kind"] == "notice"]
    assert len(notices) == 1 and "503" in notices[0]["text"]
    last = after["turns"][-1]
    assert last["kind"] == "website_rejected"  # nothing in Switzerland: no wrong-country card
    assert "Switzerland" in last["text"] and "United Kingdom" in last["text"]


def test_a_candidate_the_buyer_asks_for_in_the_chat_is_kept(
    engine: Engine, settings: Settings
) -> None:
    """The form said Switzerland; the buyer then asks for the French company: it is proposed."""
    _harness, member = setup(
        engine,
        settings,
        found(ACME, SWISS),
        model=[proposal(SWISS_ID), proposal(ACME_ID)],
    )
    session = member.open(hints={"country": "CH"})

    after = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/messages",
        json={"text": "No, the French one."},
    ).json()

    assert after["turns"][-1]["candidate"]["id"] == ACME_ID


def test_the_website_hint_is_proposed_when_a_search_under_a_new_name_finds_nothing(
    engine: Engine, settings: Settings
) -> None:
    """The buyer gives another name in the chat; the registries know nothing under it."""
    _harness, member = setup(
        engine,
        settings,
        found(ACME),
        found(),
        model=[proposal(ACME_ID), proposal(None, search_name="Acme Closures")],
    )
    session = member.open(hints={"website": WEBSITE_HOST})

    after = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/messages",
        json={"text": "No, it is Acme Closures."},
    ).json()

    last = after["turns"][-1]
    assert last["kind"] == "proposal" and last["candidate"]["id"] == WEB_ID


# --- the identity web search (spec F1: candidates from registries and web retrieval) ---------


def _cited(*urls: str) -> list[list[RetrievedUrl]]:
    return [[RetrievedUrl(url=url, snippet="a snippet that is never shown") for url in urls]]


def test_the_web_search_finds_the_website_when_the_buyers_website_does_not_respond(
    engine: Engine, settings: Settings
) -> None:
    """The Corvaglia case: no registry candidate in the country, the website times out for us,
    a web search cites pages on the buyer's website domain."""
    pages = {(WEBSITE_HOST, "/"): httpx2.Response(503)}
    harness, member = setup(
        engine,
        settings,
        found(ACME),
        model=[proposal(ACME_ID)],
        pages=pages,
        web=_cited("https://news.example/story", f"https://www.{WEBSITE_HOST}/about"),
    )

    session = member.open(
        hints={"country": "CH", "website": WEBSITE_HOST, "sector": "plastic closures"}
    )

    last = session["turns"][-1]
    assert last["kind"] == "proposal"
    assert last["candidate"]["id"] == f"web:www.{WEBSITE_HOST}"
    assert last["candidate"]["found_in"] == ["web"]
    assert last["candidate"]["country"] == "CH"
    assert "web search" in last["text"] and "Switzerland" in last["text"]
    assert "snippet" not in str(session)
    (request,) = harness.web.calls
    assert "Switzerland (CH)" in request.query.text and "plastic closures" in request.query.text
    assert ACME_ID in _others(member, session)

    confirmed = member.call(
        "POST",
        f"/identity-sessions/{session['id']}/confirm",
        json={"candidate_id": f"web:www.{WEBSITE_HOST}"},
    )
    assert confirmed.status_code == 200
    with Session(engine) as db:
        assert db.scalars(select(SupplierIdentity)).one().country == "CH"


def test_without_a_website_hint_the_web_search_takes_the_domain_carrying_the_name(
    engine: Engine, settings: Settings
) -> None:
    harness, member = setup(
        engine,
        settings,
        found(),
        web=_cited("https://directory.example/acme", "https://www.acme-closures.example/"),
    )

    session = member.open()

    last = session["turns"][-1]
    assert last["candidate"]["id"] == "web:www.acme-closures.example"
    assert last["candidate"]["website"] == "https://www.acme-closures.example/"
    assert harness.model.calls == []


def test_the_web_search_runs_once_and_a_failure_is_no_error(
    engine: Engine, settings: Settings
) -> None:
    harness, member = setup(
        engine, settings, found(), model=[], web=[RuntimeError("provider down")]
    )
    session = member.open()
    after = member.call(
        "POST", f"/identity-sessions/{session['id']}/messages", json={"text": "Try again."}
    )

    assert after.status_code == 200
    assert len(harness.web.calls) == 1
    assert after.json()["hints"] == {"website": None, "country": None, "sector": None}

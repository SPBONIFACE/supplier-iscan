"""The buyer's country and website hints when the registries offer no fitting candidate.

A candidate that contradicts the country hint is not proposed while another one fits; the website
the buyer gave becomes a candidate (once checked) when no registry candidate fits. Nothing is
discarded: every registry candidate stays under "Show other candidates".
"""

from typing import Any

import httpx2
from sqlalchemy import Engine

from app.config import Settings
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


def test_without_a_fitting_candidate_or_website_the_mismatch_is_said(
    engine: Engine, settings: Settings
) -> None:
    _harness, member = setup(engine, settings, found(ACME), model=[proposal(ACME_ID)])

    session = member.open(hints={"country": "CH"}, ui_language="fr")

    last = session["turns"][-1]
    assert last["kind"] == "proposal" and last["candidate"]["id"] == ACME_ID
    assert "(Suisse)" in last["text"] and "France" in last["text"]


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
    assert last["candidate"]["id"] == OTHER_ID  # proposed again: the mismatch is said
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

"""The identity agent (F1): registry search, one model call per turn, turns appended to the session.

Boundaries that hold here:
- code makes every outbound call (registries, website check, model); the model has no tools and
  only returns an `IdentityProposal`, which code checks against the candidates it was given;
- the member's text and the registry data reach the model as data, through the prompt set
  (`PromptSet.render`), never concatenated into instructions here;
- `ask_model` is the only place that calls the model: the redaction gate of #19 wraps it;
- prompt and completion text are never logged.
"""

import ipaddress
import json
import logging
import re
import uuid
from typing import Any

from app.db import utc_now
from app.http_client import (
    FetchError,
    InvalidUrlError,
    check_website,
    is_public_address,
    normalise_url,
)
from app.identity.candidates import entry_from_registry, entry_from_website
from app.identity.services import IdentityServices
from app.identity.strings import disclosure_text, message
from app.llm_schemas import IdentityProposal
from app.models import IdentitySession
from app.prompts import PromptSet, RenderedPrompt, log_render
from app.providers import Providers, StructuringRequest
from app.providers.metering import CallContext
from app.registries import RegistrySearchQuery, RegistrySearchResult
from app.registries.models import MAX_HINT_LENGTH, MAX_NAME_LENGTH

logger = logging.getLogger(__name__)

MAX_CANDIDATES_TO_MODEL = 10
MAX_TURNS_TO_MODEL = 20
MAX_LINKS_PER_MESSAGE = 3
_LINK = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}"


def new_turn(
    role: str, kind: str, text: str, candidate: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "role": role,
        "kind": kind,
        "text": text,
        "candidate": candidate,
        "created_at": utc_now().isoformat(),
    }


def ask_model(
    providers: Providers, rendered: RenderedPrompt, organisation_id: uuid.UUID
) -> IdentityProposal:
    """The single call site of the model for the identity chat.

    Structured output, one retry on a schema failure (inside the client), then the typed error.
    """
    client = providers.structuring()
    request = StructuringRequest(instructions=rendered.instructions, data=rendered.data)
    return client.structure(request, IdentityProposal, CallContext(organisation_id=organisation_id))


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    candidate: dict[str, Any] = entry["candidate"]
    return candidate


def hint_url(raw: str) -> str:
    """A member-given address as a ranking hint, through the guard of #15.

    The chat never fetches such an address (only `use_website` does, and the guarded transport
    vets it again at connection time); still, an address the guard would refuse is not kept: a
    private, loopback or link-local IP literal, or a local name. Raises `FetchError`.
    """
    url = normalise_url(raw, assume_https=True)
    host = url.host.strip("[]").lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise InvalidUrlError("This address is not a public website.") from None
    else:
        if not is_public_address(literal):
            raise InvalidUrlError("This address is not a public website.")
    return str(url)


def links_in(text: str) -> list[str]:
    return [match.rstrip(_TRAILING) for match in _LINK.findall(text)][:MAX_LINKS_PER_MESSAGE]


class IdentityAgent:
    def __init__(
        self, prompt_set: PromptSet, providers: Providers, services: IdentityServices
    ) -> None:
        self._prompts = prompt_set
        self._providers = providers
        self._services = services

    # --- registry search ---------------------------------------------------------------------

    def _search(
        self, session: IdentitySession, name: str, hints: dict[str, Any]
    ) -> RegistrySearchResult:
        query = RegistrySearchQuery(
            name=name[:MAX_NAME_LENGTH],
            website_hint=(hints.get("website") or None) and hints["website"][:MAX_HINT_LENGTH],
            country_hint=hints.get("country") or None,
            sector_hint=(hints.get("sector") or None) and hints["sector"][:MAX_HINT_LENGTH],
        )
        result = self._services.runner.run(self._services.registries.search(query))
        session.candidates = [entry_from_registry(c) for c in result.candidates]
        failed = set(result.failed_registries)
        session.registries = {
            "gleif": "unreachable" if "gleif" in failed else "ok",
            "wikidata": "unreachable" if "wikidata" in failed else "ok",
        }
        return result

    def _registry_notices(self, session: IdentitySession) -> list[dict[str, Any]]:
        language = session.ui_language
        down = [name for name, state in session.registries.items() if state != "ok"]
        notices: list[str] = []
        if len(down) == 2:
            notices.append(message("both_registries_down", language))
        elif down:
            notices.append(message(f"{down[0]}_down", language))
        if not session.candidates and len(down) < 2:
            notices.append(message("no_candidates", language))
        return [new_turn("assistant", "notice", text) for text in notices]

    # --- the model ---------------------------------------------------------------------------

    def _conversation(self, session: IdentitySession) -> str:
        hints = {key: value for key, value in session.hints.items() if value}
        lines = [f"supplier name: {session.name}"]
        if hints:
            lines.append(f"hints: {json.dumps(hints, ensure_ascii=False)}")
        for turn in session.transcript[-MAX_TURNS_TO_MODEL:]:
            if turn["kind"] == "disclosure":
                continue
            lines.append(f"{turn['role']}: {turn['text']}")
        return "\n".join(lines)

    def _candidates_text(self, session: IdentitySession) -> str:
        shown = [_public(entry) for entry in session.candidates[:MAX_CANDIDATES_TO_MODEL]]
        return json.dumps(shown, ensure_ascii=False)

    def _ask(self, session: IdentitySession) -> IdentityProposal | None:
        rendered = self._prompts.render(
            "identity",
            {
                "language": session.ui_language,
                "conversation": self._conversation(session),
                "candidates": self._candidates_text(session),
            },
        )
        log_render(rendered)
        session.prompt_set_hash = self._prompts.content_hash
        try:
            return ask_model(self._providers, rendered, session.organisation_id)
        except Exception as error:  # noqa: BLE001 - an agent failure is a turn, never a 500
            # The type only: an error message can quote the prompt or the completion.
            logger.warning("Identity agent call failed: %s", type(error).__name__)
            return None

    def _propose(self, session: IdentitySession, turns: list[dict[str, Any]]) -> None:
        """Ask the model about the current candidates and append its turn(s)."""
        if not session.candidates:
            return
        language = session.ui_language
        proposal = self._ask(session)
        if proposal is None:
            turns.append(new_turn("assistant", "error", message("agent_failed", language)))
            return
        if proposal.off_topic:
            text = proposal.question_to_user or message("off_topic", language)
            turns.append(new_turn("assistant", "text", text))
            return
        question = proposal.question_to_user
        wanted_name = (proposal.search_name or "").strip()
        wanted_country = (proposal.country_hint or "").strip().upper()
        if wanted_name and wanted_name.casefold() != session.name.casefold():
            hints = {**session.hints, "country": wanted_country or session.hints.get("country")}
            self._search(session, wanted_name, hints)
            turns.extend(self._registry_notices(session))
            question = None  # the model's question was about the previous candidates
        by_id = {_public(entry)["id"]: entry for entry in session.candidates}
        if not session.candidates:
            return
        # Code, not the model, decides what a proposal is: an unknown id falls back to the top rank.
        chosen = by_id.get(proposal.candidate_id or "") or session.candidates[0]
        session.current_candidate_id = _public(chosen)["id"]
        text = question or message("confirm_question", language)
        turns.append(new_turn("assistant", "proposal", text, _public(chosen)))

    # --- operations --------------------------------------------------------------------------

    def start(self, session: IdentitySession) -> None:
        """First turns of a new session: disclosure, registry notices, first proposal."""
        turns = [new_turn("assistant", "disclosure", disclosure_text(session.ui_language))]
        self._search(session, session.name, session.hints)
        turns.extend(self._registry_notices(session))
        self._propose(session, turns)
        session.transcript = [*session.transcript, *turns]
        session.last_message_at = utc_now()

    def correct(self, session: IdentitySession, text: str) -> None:
        """A free-text correction: guard its links, search again if asked, propose again."""
        turns = [new_turn("user", "text", text)]
        hints = dict(session.hints)
        for link in links_in(text):
            try:
                hints["website"] = hint_url(link)
                break
            except FetchError:
                turns.append(
                    new_turn("assistant", "notice", message("link_ignored", session.ui_language))
                )
        hints_changed = hints != session.hints
        session.hints = hints
        session.transcript = [*session.transcript, *turns]
        proposal_turns: list[dict[str, Any]] = []
        if hints_changed or not session.candidates:
            # New hints re-rank (the registry answers are cached by name, hints never reach the
            # cache); with no candidate at all, searching again is the only way forward.
            self._search(session, session.name, session.hints)
            proposal_turns.extend(self._registry_notices(session))
        self._propose(session, proposal_turns)
        session.transcript = [*session.transcript, *proposal_turns]
        session.last_message_at = utc_now()

    def use_website(self, session: IdentitySession, raw: str) -> None:
        """ "None of these": the domain is checked by the guarded client and must respond."""
        language = session.ui_language
        turns = [new_turn("user", "text", raw)]
        result = check_website(raw, self._services.http)
        if result.status != "reachable" or not result.final_url or not result.final_domain:
            reason = result.reason or ""
            turns.append(
                new_turn(
                    "assistant",
                    "website_rejected",
                    message("website_rejected", language, reason=reason),
                )
            )
        else:
            entry = entry_from_website(session.name, result.final_url, result.final_domain)
            session.candidates = [entry, *session.candidates]
            session.current_candidate_id = _public(entry)["id"]
            turns.append(
                new_turn(
                    "assistant", "proposal", message("website_proposal", language), _public(entry)
                )
            )
        session.transcript = [*session.transcript, *turns]
        session.last_message_at = utc_now()

"""The gate in front of the providers (#19): raw strings refused, no call can skip it, and the
identity chat, source storage and a paused run all honour it."""

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.collection.source_store import SourceRecord, store_source
from app.config import Settings
from app.db import Database, utc_now
from app.models import IdentitySession, Source, SupplierIdentity, SuppressionEntry
from app.providers import Providers, RetrievalRequest, StructuringRequest
from app.providers.fake import FakeRetrievalAdapter, FakeStructuringAdapter, fake_adapters
from app.providers.interface import RetrievedUrl
from app.providers.metering import CallContext
from app.redaction import (
    RedactedText,
    RedactionGate,
    RedactionUnavailable,
    Redactor,
)
from app.redaction import engine as engine_module
from tests.factories import create_organisation
from tests.identity.support import candidate, found, proposal
from tests.identity.test_identity import setup
from tests.providers.support import SENTINEL_KEY, Company, catalogue, config, make_meter
from tests.redaction.measure_detector import load
from tests.redaction.support import fake_redactor
from tests.runs_support import create_run

APP = Path(__file__).resolve().parents[2] / "app"
CONTEXT = CallContext(organisation_id=uuid.uuid4())
SEEDED = (
    "anna.keller@keller-gmbh.example",
    "+49 30 1234567",
    "Anna Keller-Brandt",
    "Zoë Okonkwo-Lindqvist",
)
SEEDED_TEXT = (
    "Anna Keller-Brandt (anna.keller@keller-gmbh.example, +49 30 1234567) "
    "met Zoë Okonkwo-Lindqvist."
)


def providers_with(
    structuring: FakeStructuringAdapter | None = None,
    retrieval: FakeRetrievalAdapter | None = None,
) -> Providers:
    cat = catalogue(config("primary"))
    adapters = fake_adapters(cat, structuring=structuring, retrieval=retrieval)
    return Providers(cat, {"GEMINI_API_KEY": SENTINEL_KEY}, adapters, meter=make_meter())


def gate(names: tuple[str, ...] = ()) -> RedactionGate:
    return RedactionGate(
        lambda: names, fake_redactor("Anna Keller-Brandt", "Zoë Okonkwo-Lindqvist")
    )


def assert_clean(text: str) -> None:
    for item in SEEDED:
        assert item not in text, item


# --- the provider interface refuses raw strings ---


def test_a_raw_string_is_refused_by_both_requests_at_run_time() -> None:
    with pytest.raises(TypeError):
        StructuringRequest(instructions="i", data="Anna Keller-Brandt")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RetrievalRequest(instructions="i", query="Anna Keller-Brandt")  # type: ignore[arg-type]


def test_a_request_edited_after_its_creation_is_refused_by_the_client_and_nothing_is_sent() -> None:
    fake = FakeStructuringAdapter(['{"legal_name": "Acme", "country": "FR"}'])
    retrieval = FakeRetrievalAdapter([[RetrievedUrl(url="https://a.example")]])
    providers = providers_with(fake, retrieval)
    request = StructuringRequest(instructions="i", data=gate().redact("hello"))
    object.__setattr__(request, "data", SEEDED_TEXT)  # a frozen dataclass can still be forced
    search = RetrievalRequest(instructions="i", query=gate().redact("hello"))
    object.__setattr__(search, "query", SEEDED_TEXT)

    with pytest.raises(TypeError):
        providers.structuring().structure(request, Company, CONTEXT)
    with pytest.raises(TypeError):
        providers.retrieval().retrieve(search, CONTEXT)

    assert fake.calls == [] and retrieval.calls == []


def test_personal_data_in_sources_and_buyer_criteria_never_reaches_the_provider() -> None:
    fake = FakeStructuringAdapter(['{"legal_name": "Acme", "country": "FR"}'] * 2)
    retrieval = FakeRetrievalAdapter([[RetrievedUrl(url="https://a.example")]])
    providers = providers_with(fake, retrieval)
    source = f"About us. {SEEDED_TEXT} Acme Supplies SA makes valves."
    criteria = f"Prefer suppliers where {SEEDED[2]} is not a director; contact {SEEDED[0]}."

    providers.structuring().structure(
        StructuringRequest("extract", gate().redact(source)), Company, CONTEXT
    )
    providers.structuring().structure(
        StructuringRequest("assess", gate().redact(criteria)), Company, CONTEXT
    )
    providers.retrieval().retrieve(
        RetrievalRequest("find", gate().redact(f"annual report {SEEDED_TEXT}")), CONTEXT
    )

    sent = [call.data.text for call in fake.calls] + [call.query.text for call in retrieval.calls]
    assert len(sent) == 3
    for text in sent:
        assert_clean(text)
    assert "Acme Supplies SA" in sent[0]


def test_the_gate_applies_the_suppression_names_it_is_given() -> None:
    out = gate(("anna keller-brandt",)).redact("ANNA KELLER-BRANDT signed.")

    assert out.text == "[…] signed."


# --- policy: no provider call can bypass the gate ---


def python_files() -> list[Path]:
    return [path for path in sorted(APP.rglob("*.py"))]


def relative(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def test_only_the_redaction_module_creates_redacted_text() -> None:
    offenders = []
    for path in python_files():
        if relative(path).startswith("redaction/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            named = (
                node.func.id
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                else None
            )
            if named in {"RedactedText", "mint"} or (
                isinstance(node, ast.ImportFrom)
                and any(alias.name in {"mint", "_MINT"} for alias in node.names)
            ):
                offenders.append(relative(path))
    assert offenders == []


def test_adapters_are_called_only_by_the_provider_clients() -> None:
    """`generate_json` and `search` on an adapter are called in interface.py and nowhere else, so
    the type check of the clients cannot be walked around."""
    callers = set()
    for path in python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"generate_json"}
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "search"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "_adapter"
                )
            ):
                callers.add(relative(path))
    assert callers == {"providers/interface.py"}


def test_every_request_is_built_from_a_gate_result_never_from_a_literal() -> None:
    """The places that build provider requests are the identity agent and the retrieval step of
    collection (#20), each with the result of `gate.redact`. A new call site must be added here on
    purpose, and be reviewed."""
    builders: dict[str, list[str]] = {}
    for path in python_files():
        if relative(path).startswith("providers/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"StructuringRequest", "RetrievalRequest"}
            ):
                builders.setdefault(relative(path), []).append(node.func.id)
                for keyword in node.keywords:
                    if keyword.arg in {"data", "query"}:
                        assert not isinstance(keyword.value, ast.Constant | ast.JoinedStr)
    assert builders == {
        "identity/agent.py": ["StructuringRequest"],
        "collection/retrieval.py": ["RetrievalRequest"],
        "extraction/stage.py": ["StructuringRequest"],
        "assessment/stage.py": ["StructuringRequest"],
    }


def test_the_retrieval_step_redacts_before_it_builds_the_request() -> None:
    source = (APP / "collection" / "retrieval.py").read_text(encoding="utf-8")
    function = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "retrieve"
    )
    found = sorted(
        (node.lineno, node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id)  # type: ignore[attr-defined]
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    )
    calls = [name for _line, name in found]  # in source order
    assert calls.index("redact") < calls.index("RetrievalRequest") < calls.index("retrieve")


def test_the_identity_agent_redacts_before_it_builds_the_request() -> None:
    source = (APP / "identity" / "agent.py").read_text(encoding="utf-8")
    function = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "ask_model"
    )
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id  # type: ignore[attr-defined]
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    assert calls.index("redact") < calls.index("StructuringRequest") < calls.index("structure")


def test_extraction_redacts_the_stored_source_text_again_before_it_builds_the_request() -> None:
    """The stored text is already redacted, but the only way to a `RedactedText` is the gate: the
    extraction call site passes the rendered data through `gate.redact` (no new route into the
    provider interface), and it is the only function there that calls the model."""
    source = (APP / "extraction" / "stage.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "ask"
    )
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id  # type: ignore[attr-defined]
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    assert calls.index("redact") < calls.index("StructuringRequest") < calls.index("structure")
    structure_callers = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "structure"
            for call in ast.walk(node)
        )
    )
    assert structure_callers == ["ask"]


def test_assessment_redacts_the_facts_again_before_it_builds_the_request() -> None:
    """The assessment call site (#25) is `ask`: the rendered data (facts, buyer context) passes
    through `gate.redact` before the request is built, and `ask` is the only function there that
    calls the model."""
    source = (APP / "assessment" / "stage.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "ask"
    )
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id  # type: ignore[attr-defined]
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    assert calls.index("redact") < calls.index("StructuringRequest") < calls.index("structure")
    structure_callers = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "structure"
            for call in ast.walk(node)
        )
    )
    assert structure_callers == ["ask"]


def test_fit_and_recommendation_drafting_reach_the_model_only_through_the_assessment_call_site() -> (
    None
):
    """Fit and the recommendations redraft (#26) add no call site: the worker job builds no
    request and calls no provider itself; the criteria and the buyer context are values of the
    prompt that `draft_part` hands to `ask`, which redacts them before the request is built."""
    source = (APP / "assessment" / "drafting.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id  # type: ignore[attr-defined]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "draft_part" in called
    assert not called & {"StructuringRequest", "RetrievalRequest", "structure", "retrieve"}
    for path in (APP / "buyer").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "StructuringRequest" not in text and ".structure(" not in text, path.name
    stage = ast.parse((APP / "assessment" / "stage.py").read_text(encoding="utf-8"))
    draft_part = next(
        node
        for node in ast.walk(stage)
        if isinstance(node, ast.FunctionDef) and node.name == "draft_part"
    )
    inside = [
        node.func.id  # type: ignore[attr-defined]
        for node in ast.walk(draft_part)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "_ask_safely" in inside  # the one route from `draft_part` to `ask`


# --- the identity chat ---


def test_chat_turns_and_candidates_reach_the_model_redacted(
    engine: Engine, settings: Settings
) -> None:
    acme = candidate()
    other = candidate(
        "Acme Holdings Ltd",
        legal_name="Acme Holdings Ltd",
        lei="213800OTHER0000000AA",
        wikidata_id="Q2",
        registries=("gleif",),
    )
    sole = candidate(
        "Okonkwo-Lindqvist Zoë",
        legal_name="Zoë Okonkwo-Lindqvist",
        legal_form="Einzelunternehmer",
        lei="213800SOLE00000000AA",
        wikidata_id=None,
        registries=("gleif",),
    )
    harness, member = setup(
        engine,
        settings,
        found(acme, other, sole),
        model=[proposal("lei:529900ACME00000000AA")] * 3,
    )
    session = member.open(name="Anna Keller-Brandt")

    member.call("POST", f"/identity-sessions/{session['id']}/messages", json={"text": SEEDED_TEXT})

    assert len(harness.model.calls) == 2
    for call in harness.model.calls:
        assert_clean(call.data.text)
        assert "Acme Supplies SA" in call.data.text and "Acme Holdings Ltd" in call.data.text
    # The transcript keeps the member's free text (spec); only what goes to the model is redacted.
    with Session(engine) as db:
        transcript = db.scalars(select(IdentitySession)).one().transcript
    assert any(turn["text"] == SEEDED_TEXT for turn in transcript)


def test_if_redaction_fails_the_identity_chat_sends_nothing(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, member = setup(
        engine, settings, found(candidate()), model=[proposal("lei:529900ACME00000000AA")]
    )

    def broken(self: Redactor, text: str, context: object = None) -> RedactedText:
        raise RedactionUnavailable

    monkeypatch.setattr(Redactor, "redact", broken)

    session = member.open(name="Anna Keller-Brandt")

    assert harness.model.calls == []  # nothing went to the provider, and no fallback to raw text
    assert session["turns"][-1]["kind"] == "error"


# --- storage ---


def stored_texts(engine: Engine) -> str:
    with Session(engine) as db:
        return "\n".join(f"{s.redacted_text}\n{s.author}" for s in db.scalars(select(Source)))


@pytest.mark.model
def test_a_seeded_corpus_leaves_no_email_phone_or_name_in_the_database(
    engine: Engine, real_redactor: Redactor
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)
    database = Database(None, engine)
    with Session(engine) as db:
        db.add(SuppressionEntry(kind="person_name", value="Tobias Reuter"))
        db.commit()

    cases = [i for i in load("fresh", "names") if i["ctx"] == "prose" and i["style"] == "normal"]
    for number, case in enumerate(cases):
        text = case["text"] + (" TOBIAS REUTER." if case["lang"] == "de" else "")
        store_source(
            database,
            run_id,
            organisation_id,
            SourceRecord(
                f"https://site.example/{number}", utc_now(), "text/html", text, "Anna Keller-Brandt"
            ),
        )

    everything = stored_texts(engine)
    for case in cases:
        for start, end in case["spans"]:
            assert case["text"][start:end] not in everything, case["text"][start:end]
    assert "Anna Keller-Brandt" not in everything
    assert "TOBIAS REUTER" not in everything and "Tobias Reuter" not in everything


def test_a_natural_persons_name_is_redacted_in_stored_text_a_companys_is_not(
    engine: Engine,
) -> None:
    organisation_id = create_organisation(engine)
    database = Database(None, engine)
    person_run = create_run(engine, organisation_id, legal_name="Marlene Quast-Ekdahl")
    company_run = create_run(engine, organisation_id, legal_name="Quast Ekdahl Bau GmbH")
    with Session(engine) as db:
        db.execute(
            update(SupplierIdentity)
            .where(SupplierIdentity.legal_name == "Marlene Quast-Ekdahl")
            .values(natural_person=True)
        )
        db.commit()
    text = "marlene quast-ekdahl runs Quast Ekdahl Bau GmbH from Hamburg."

    for run_id in (person_run, company_run):
        store_source(
            database,
            run_id,
            organisation_id,
            SourceRecord(f"https://site.example/{run_id}", utc_now(), "text/html", text),
        )

    with Session(engine) as db:
        rows = {s.run_id: s.redacted_text for s in db.scalars(select(Source))}
    assert "quast-ekdahl" not in rows[person_run].lower()
    assert "Quast Ekdahl Bau GmbH" in rows[person_run]
    assert "Quast Ekdahl Bau GmbH" in rows[company_run]


def test_if_redaction_fails_nothing_is_stored(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)
    monkeypatch.setattr(engine_module.Redactor, "_person_spans", _raise)

    with pytest.raises(RedactionUnavailable) as error:
        store_source(
            Database(None, engine),
            run_id,
            organisation_id,
            SourceRecord("https://site.example/a", utc_now(), "text/html", SEEDED_TEXT),
        )

    assert_clean(str(error.value))
    with Session(engine) as db:
        assert db.scalars(select(Source)).all() == []


def _raise(self: Redactor, text: str) -> list[tuple[int, int]]:
    raise RuntimeError(text)


def test_the_suppression_reader_failing_stops_the_call() -> None:
    def unreadable() -> list[str]:
        raise RuntimeError("database down")

    with pytest.raises(RedactionUnavailable):
        RedactionGate(unreadable, fake_redactor()).redact("hello")

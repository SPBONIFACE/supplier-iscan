"""One trace per run, across the API and the worker (#51), and no personal data in the telemetry.

Fake provider, in-memory exporters, a throwaway PostgreSQL: nothing leaves the process.
"""

import json
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database
from app.models import Job, ProfileRun
from app.providers.fake import FakeStructuringAdapter
from app.providers.interface import StructuringOutput, StructuringRequest
from app.providers.metering import CallUsage
from app.runs.stages import DEFAULT_STAGES, Stage, StageContext
from app.telemetry import TRACEPARENT, failure_rate
from app.worker import work_once
from tests.auth_support import send_with_session
from tests.extraction.support import providers_with
from tests.factories import create_session, create_user
from tests.providers.support import SENTINEL_KEY, Company
from tests.redacted import redacted
from tests.runs_support import create_identity
from tests.support import make_client
from tests.telemetry.conftest import Recording

SETTINGS = Settings(database_url=None, allowed_origins=("http://localhost:5173",))

# Values that must never appear in a span, a metric or a log.
EMAIL = "zoltan.sentinelbaum@sentinel-mail.example"
PHONE = "+33198765432"
PERSON = "Zoltan Sentinelbaum"
SUPPLIER = "Sentinel Supplier Holdings"
URL = "https://sentinel-supplier.example/private/path"
QUOTE = "sentinel verbatim quote about the supplier"
PROMPT = "SENTINEL-PROMPT-TEXT"
COMPLETION = "SENTINEL-COMPLETION-TEXT"
BUYER_TEXT = "sentinel buyer free text"
TOKEN = "SENTINEL-INVITATION-TOKEN"  # noqa: S105 - a test value
SENTINELS = [
    EMAIL, PHONE, PERSON, SUPPLIER, URL, QUOTE, SENTINEL_KEY, PROMPT, COMPLETION, BUYER_TEXT, TOKEN,
]  # fmt: skip


def stages(adapter_text: str = COMPLETION, fail_collection: bool = False) -> dict[str, Stage]:
    def collection(context: StageContext) -> None:
        if fail_collection:
            raise RuntimeError(f"boom {EMAIL} {PHONE} {URL} {QUOTE} {SENTINEL_KEY}")

    def extraction(context: StageContext) -> None:
        assert context.providers is not None
        request = StructuringRequest(
            instructions=PROMPT,
            data=redacted(f"{SUPPLIER} {PERSON} {EMAIL} {PHONE} {URL} {QUOTE} {BUYER_TEXT}"),
        )
        context.providers.structuring().structure(request, Company, context.call_context)

    return {**DEFAULT_STAGES, "collection": collection, "extraction": extraction}


def good_adapter() -> FakeStructuringAdapter:
    output = StructuringOutput(
        json.dumps({"legal_name": COMPLETION, "country": "FR"}),
        CallUsage(input_tokens=120, output_tokens=40, reasoning_tokens=10),
    )
    return FakeStructuringAdapter([output])


def start_run(client: TestClient, engine: Engine) -> uuid.UUID:
    user = create_user(engine)
    token = create_session(engine, user.id)
    identity = create_identity(
        engine, user.organisation_id, legal_name=SUPPLIER, website=URL, country="FR"
    )
    response = send_with_session(
        client, "POST", "/runs", token, json={"identity_id": str(identity)}
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["id"])


def work(engine: Engine, adapter: FakeStructuringAdapter, **kwargs: Any) -> None:
    providers = providers_with(adapter)
    while work_once(
        Database(None, engine), SETTINGS, "worker-t", stages(**kwargs), providers=providers
    ):
        pass


def test_one_trace_covers_the_request_the_queue_the_stages_and_the_provider_call(
    client: TestClient, engine: Engine, recording: Recording
) -> None:
    run_id = start_run(client, engine)
    with Session(engine) as db:
        job = db.scalars(select(Job)).one()
    traceparent = job.payload[TRACEPARENT]  # stored with the queued job
    work(engine, good_adapter())

    spans = recording.spans()
    names = [span.name for span in spans]
    assert "POST /runs" in names and "job.process" in names and "run.execute" in names
    assert sorted(
        str(span.attributes["iscan.stage"])  # type: ignore[index]
        for span in spans
        if span.name == "run.stage"
    ) == ["assessment", "collection", "extraction", "identity"]
    assert names.count("provider.call") == 1
    # One trace ID for all of them, and it is the one stored with the job.
    trace_ids = {span.context.trace_id for span in spans}
    assert len(trace_ids) == 1
    assert traceparent.split("-")[1] == format(trace_ids.pop(), "032x")
    # The worker's job span is a child of the request span, the provider call of its stage.
    by_name = {span.name: span for span in spans}
    assert by_name["job.process"].parent is not None
    assert by_name["job.process"].parent.span_id == by_name["POST /runs"].context.span_id
    stage_ids = {span.context.span_id for span in spans if span.name == "run.stage"}
    assert by_name["provider.call"].parent is not None
    assert by_name["provider.call"].parent.span_id in stage_ids
    # The request span carries the route template and the status, nothing more.
    assert by_name["POST /runs"].attributes == {
        "http.request.method": "POST",
        "http.route": "/runs",
        "http.response.status_code": 202,
    }
    with Session(engine) as db:
        assert db.get(ProfileRun, run_id).status == "completed"  # type: ignore[union-attr]


def test_logs_are_json_with_the_trace_of_the_run(
    client: TestClient, engine: Engine, recording: Recording
) -> None:
    start_run(client, engine)
    work(engine, good_adapter(), fail_collection=True)

    failures = [entry for entry in recording.logs() if "failed in stage" in entry["message"]]
    (failure,) = failures
    trace_id = recording.spans()[0].context.trace_id
    assert failure["trace_id"] == format(trace_id, "032x")
    assert len(failure["span_id"]) == 16
    assert {"timestamp", "level", "service", "logger", "message"} <= failure.keys()
    assert failure["service"] == "test" and failure["level"] == "ERROR"
    assert failure["error_type"] == "RuntimeError"
    # A span event on the run's trace for the same failure, with the error type only.
    events = [
        event for span in recording.spans() for event in span.events if event.name == "failure"
    ]
    assert any(
        event.attributes and event.attributes.get("exception.type") == "RuntimeError"
        for event in events
    )
    assert any(span.status.status_code.name == "ERROR" for span in recording.spans())


def test_a_provider_failure_gives_a_log_entry_and_a_span_event(
    client: TestClient, engine: Engine, recording: Recording
) -> None:
    start_run(client, engine)
    work(engine, FakeStructuringAdapter([ConnectionError(f"down {URL} {SENTINEL_KEY}")]))

    (call,) = [span for span in recording.spans() if span.name == "provider.call"]
    assert [event.name for event in call.events] == ["failure"]
    assert call.status.status_code.name == "ERROR"
    logged = [entry for entry in recording.logs() if "Provider call failed" in entry["message"]]
    assert logged and logged[0]["trace_id"] == format(call.context.trace_id, "032x")


def test_metrics_count_runs_stages_llm_usage_and_the_failure_rate(
    client: TestClient, engine: Engine, recording: Recording
) -> None:
    start_run(client, engine)
    work(engine, good_adapter())
    start_run(client, engine)
    work(engine, good_adapter(), fail_collection=True)

    assert [int(point.value) for point in recording.points("iscan.runs.started")] == [2]
    finished = recording.finished_by_status()
    assert finished == {"completed": 1, "failed": 1}
    assert failure_rate(finished) == 0.5
    stage_points = recording.points("iscan.run.stage.duration")
    assert {point.attributes["iscan.stage"] for point in stage_points} >= {"identity", "extraction"}
    tokens = {
        point.attributes["iscan.token_type"]: int(point.value)
        for point in recording.points("iscan.llm.tokens")
    }
    assert tokens == {"input": 120, "output": 40, "reasoning": 10}
    (cost,) = recording.points("iscan.llm.cost")
    assert cost.value > 0 and cost.attributes["iscan.role"] == "structuring"
    (calls,) = recording.points("iscan.llm.calls")
    assert calls.attributes["iscan.outcome"] == "success"
    requests = {
        (point.attributes["http.route"], point.attributes["http.response.status_code"])
        for point in recording.points("iscan.http.requests")
    }
    assert ("/runs", 202) in requests


def test_a_run_that_is_paused_is_not_a_finished_run(
    client: TestClient, engine: Engine, recording: Recording
) -> None:
    start_run(client, engine)
    work(engine, FakeStructuringAdapter([ConnectionError("down")]))

    assert recording.finished_by_status() == {}
    assert failure_rate(recording.finished_by_status()) is None


def test_the_sentinel_values_are_in_no_span_metric_or_log(
    client: TestClient, engine: Engine, recording: Recording
) -> None:
    # Requests that carry the sentinels in a body, a query string and a path.
    client.post(
        "/runs",
        json={"identity_id": "not-an-id", "email": EMAIL, "note": BUYER_TEXT, "quote": QUOTE},
    )
    client.get(f"/invitations/{TOKEN}", params={"email": EMAIL, "phone": PHONE})
    client.get(f"/{PERSON.replace(' ', '-')}/{PHONE}")
    # Three runs: completed, failed with sentinels in the exception, paused on a provider failure.
    start_run(client, engine)
    work(engine, good_adapter())
    start_run(client, engine)
    work(engine, good_adapter(), fail_collection=True)
    start_run(client, engine)
    work(engine, FakeStructuringAdapter([ConnectionError(f"{EMAIL} {URL} {SENTINEL_KEY} {QUOTE}")]))

    seen = recording.everything()
    # The telemetry is not empty: the sentinels are absent, not unobserved.
    assert len(recording.spans()) > 15 and len(recording.logs()) > 3
    assert recording.finished_by_status() == {"completed": 1, "failed": 1}
    assert "provider.call" in seen and "iscan.llm.tokens" in seen
    for sentinel in SENTINELS:
        assert sentinel not in seen, f"{sentinel!r} reached the telemetry"


def test_a_request_without_a_collector_header_starts_its_own_trace(
    client: TestClient, recording: Recording
) -> None:
    caller = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    client.get("/health", headers={"traceparent": caller})

    (span,) = recording.spans()
    assert format(span.context.trace_id, "032x") != caller.split("-")[1]


def test_make_client_is_unaffected_by_the_middleware(recording: Recording) -> None:
    client = make_client(database_check=lambda: True)

    assert client.get("/health").status_code == 200
    (span,) = recording.spans()
    assert span.name == "GET /health"

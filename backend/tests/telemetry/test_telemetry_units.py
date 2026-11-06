"""Telemetry (#51): the allow-list, JSON logs, SDK debug logging off, configuration, an unreachable
collector, the database statement timeout, the first-start administrator line."""

import logging
import socket
import time
from collections.abc import Iterator
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.config import ConfigurationError, Settings, load_settings
from app.db import make_engine
from app.main import create_app
from app.providers.interface import StructuringClient, StructuringRequest
from app.telemetry import (
    TRACEPARENT,
    context_from_traceparent,
    core,
    current_traceparent,
    failure_rate,
    span,
)
from app.telemetry.logs import SDK_LOG_VARIABLES, configure_logging
from app.telemetry.setup import build_telemetry
from tests.providers.support import CONTEXT, SENTINEL_KEY, Company, Recorder, fixture, make_meter
from tests.providers.test_adapters import STRUCTURING_CASES
from tests.redacted import redacted
from tests.support import BASE_URL, make_client
from tests.telemetry.conftest import Recording

BASE = {"database_url": None, "allowed_origins": ("http://localhost:5173",)}


# --- the allow-list ----------------------------------------------------------------------------


def test_attributes_come_from_an_allow_list_and_a_safe_character_set() -> None:
    attributes = core.span_attributes(
        {
            "http.route": "/runs/{id}",
            "iscan.model_id": "claude-sonnet-4.5",
            "iscan.attempt": 2,
            "email": "a@b.example",  # not in the list
            "iscan.provider": "bad value with spaces and an @",  # in the list, unsafe value
            "iscan.stage": "https://supplier.example/x?y=1",
            "iscan.role": None,
        }
    )

    assert attributes == {
        "http.route": "/runs/{id}",
        "iscan.model_id": "claude-sonnet-4.5",
        "iscan.attempt": 2,
    }
    assert core.metric_attributes({"iscan.run_id": "x", "iscan.role": "retrieval"}) == {
        "iscan.role": "retrieval"
    }


def test_the_failure_rate_is_failed_runs_over_finished_runs() -> None:
    assert failure_rate({"completed": 6, "partial": 1, "stopped": 1, "failed": 2}) == 0.2
    assert failure_rate({"failed": 3}) == 1.0
    assert failure_rate({}) is None  # no run finished: no rate, so no alert


# --- JSON logs ---------------------------------------------------------------------------------


def test_a_log_entry_has_the_fixed_fields_and_the_ids_of_the_current_span(
    recording: Recording,
) -> None:
    logger = logging.getLogger("tests.telemetry")
    logger.info("outside")
    with span("work") as current:
        logger.warning("inside %s", "value")
        try:
            raise ValueError("secret@example.test https://x.example")
        except ValueError:
            logger.error("boom", exc_info=True)

    outside, inside, error = recording.logs()
    assert "trace_id" not in outside
    context = current.get_span_context()
    assert inside["trace_id"] == format(context.trace_id, "032x")
    assert inside["span_id"] == format(context.span_id, "016x")
    assert (inside["service"], inside["level"], inside["message"]) == (
        "test",
        "WARNING",
        "inside value",
    )
    assert error["error_type"] == "ValueError"
    assert "secret@example.test" not in recording.stream.getvalue()
    assert inside["timestamp"].endswith("+00:00")


def test_the_application_loggers_write_under_plain_uvicorn(recording: Recording) -> None:
    # uvicorn gives its loggers their own handler and stops propagation: undone by the setup.
    logging.getLogger("uvicorn.error").propagate = False
    logging.getLogger("uvicorn.error").addHandler(logging.NullHandler())
    configure_logging("test", recording.stream)

    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("app.auth.bootstrap").info("Local administrator created")

    assert [entry["message"] for entry in recording.logs()] == [
        "Application startup complete.",
        "Local administrator created",
    ]


def test_the_first_start_administrator_line_is_json_and_holds_no_credential(
    engine: Engine, settings: Settings, recording: Recording
) -> None:
    password = "Sentinel-Admin-Pass-93!"
    configured = Settings(
        **{**settings.__dict__, "admin_email": "admin@sentinel.example", "admin_password": password}
    )

    with TestClient(create_app(configured, engine=engine), base_url=BASE_URL):
        pass

    lines = [
        entry for entry in recording.logs() if "Local administrator created" in entry["message"]
    ]
    assert len(lines) == 1 and lines[0]["level"] == "INFO"
    assert password not in recording.stream.getvalue()
    assert "admin@sentinel.example" not in recording.stream.getvalue()


# --- SDK debug logging stays off ---------------------------------------------------------------


@pytest.mark.parametrize("case", STRUCTURING_CASES[:2], ids=lambda case: case.provider)
def test_sdk_debug_logging_never_writes_a_prompt(
    case: object, recording: Recording, monkeypatch: pytest.MonkeyPatch
) -> None:
    for variable in SDK_LOG_VARIABLES:
        monkeypatch.setenv(variable, "debug")
    configure_logging("test", recording.stream)  # what the API and the worker do at start
    import os

    assert not any(variable in os.environ for variable in SDK_LOG_VARIABLES)
    # An operator who still got an SDK logger to DEBUG (the SDK ran its own set-up first).
    sdk_loggers = ("anthropic", "httpx", "httpx2", "httpcore", "google_genai", "openai")
    for name in sdk_loggers:
        monkeypatch.setattr(logging.getLogger(name), "level", logging.DEBUG)
    prompt_logger = logging.getLogger("anthropic._base_client")
    prompt_logger.debug("Request options: %s", {"json_data": {"messages": "SENTINEL-PROMPT"}})
    logging.getLogger("httpx2").info("HTTP Request: POST https://acme.example/secret 200")

    recorder = Recorder([(200, fixture(f"{case.provider}.json")["structuring"])])  # type: ignore[attr-defined]
    cfg, client = case.build(recorder)  # type: ignore[attr-defined]
    structuring = StructuringClient(cfg, case.adapter(cfg, client), make_meter())  # type: ignore[attr-defined]
    structuring.structure(
        StructuringRequest(instructions="SENTINEL-PROMPT", data=redacted("SENTINEL-DATA")),
        Company,
        CONTEXT,
    )

    written = recording.stream.getvalue()
    assert (
        "SENTINEL" not in written and "acme.example" not in written and SENTINEL_KEY not in written
    )


# --- traceparent -------------------------------------------------------------------------------


def test_the_trace_context_round_trips_through_a_job_payload(recording: Recording) -> None:
    assert current_traceparent() is None
    with span("request") as request:
        traceparent = current_traceparent()
    assert traceparent is not None
    context = context_from_traceparent(traceparent)
    with span("job", parent=context) as job:
        pass

    assert request.get_span_context().trace_id == job.get_span_context().trace_id
    assert TRACEPARENT == "traceparent"
    assert context_from_traceparent("garbage") is None
    assert context_from_traceparent(None) is None
    assert context_from_traceparent("00-" + "0" * 32 + "-" + "0" * 16 + "-01") is None


# --- configuration -----------------------------------------------------------------------------


def test_no_endpoint_means_nothing_is_exported() -> None:
    settings = load_settings({})

    telemetry = build_telemetry("api", settings)

    assert settings.telemetry_endpoint is None
    processors = telemetry.tracer_provider._active_span_processor._span_processors
    assert processors == ()


def test_the_endpoint_and_the_timeout_are_settings_read_by_name() -> None:
    settings = load_settings(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/",
            "TELEMETRY_EXPORT_TIMEOUT_SECONDS": "2",
        }
    )

    assert settings.telemetry_endpoint == "http://collector:4318"
    assert settings.telemetry_export_timeout_seconds == 2
    with pytest.raises(ConfigurationError, match="OTEL_EXPORTER_OTLP_ENDPOINT") as error:
        load_settings({"OTEL_EXPORTER_OTLP_ENDPOINT": "ftp://user:secret@collector"})
    assert "secret" not in str(error.value)


# --- an unreachable collector ------------------------------------------------------------------


@pytest.fixture
def black_hole() -> Iterator[str]:
    """A local server that accepts connections and never answers."""
    with closing(socket.socket()) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(16)
        yield f"http://127.0.0.1:{server.getsockname()[1]}"


def test_a_collector_that_never_answers_does_not_slow_or_fail_requests(black_hole: str) -> None:
    settings = Settings(**BASE, telemetry_endpoint=black_hole, telemetry_export_timeout_seconds=1)  # type: ignore[arg-type]
    telemetry = build_telemetry("api", settings)
    previous = core.install(telemetry)
    try:
        client = make_client(database_check=lambda: True)
        started = time.monotonic()
        statuses = [client.get("/health").status_code for _ in range(30)]
        for _ in range(200):  # runs and provider calls record metrics and spans too
            with span("run.stage"):
                telemetry.run_finished("completed")
        elapsed = time.monotonic() - started
    finally:
        core.install(previous)
        started = time.monotonic()
        telemetry.shutdown()  # abandons the export after the timeout
        shutdown = time.monotonic() - started

    assert statuses == [200] * 30
    assert elapsed < 2
    assert shutdown < 10


# --- database timeouts (QA note of #8) ---------------------------------------------------------


def test_a_statement_that_does_not_finish_is_cancelled(database_url: str) -> None:
    engine = make_engine(database_url, statement_timeout_seconds=1)
    try:
        started = time.monotonic()
        with pytest.raises(OperationalError), engine.connect() as connection:
            connection.execute(text("SELECT pg_sleep(5)"))
        assert time.monotonic() - started < 4
    finally:
        engine.dispose()


def test_the_statement_timeout_is_a_setting() -> None:
    assert load_settings({}).database_statement_timeout_seconds == 30
    settings = load_settings({"DATABASE_STATEMENT_TIMEOUT_SECONDS": "7"})
    assert settings.database_statement_timeout_seconds == 7

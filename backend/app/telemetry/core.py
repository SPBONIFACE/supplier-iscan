"""Traces and metrics (#51): one `Telemetry` object holds the providers and the instruments.

Rules that make the telemetry safe by construction:

- Attributes come from an allow-list (`SPAN_ATTRIBUTES`, `METRIC_ATTRIBUTES`) and their values from
  a conservative character set. Anything else is dropped, so a name, an e-mail address, a quote or
  a URL given by mistake never leaves the process. Nothing is built from a request body, a prompt
  or a source text.
- An exception is recorded by its type only (`exception.type`), never its message: SDK errors can
  quote the request.
- Our own providers are used, not the global ones: the traces that SDKs of other packages emit
  (for instance the Mistral client's) go to the no-op global provider and are never exported.
- With no endpoint, nothing is exported; spans still exist, so that the logs carry a `trace_id`.
- Export runs in background threads (batch span processor, periodic metric reader) with a short
  timeout and a bounded queue: an unreachable collector never slows or fails a request or a run.
"""

import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

INSTRUMENTATION_NAME = "supplier_iscan"
TRACEPARENT = "traceparent"  # key in the payload of a queued job

SPAN_ATTRIBUTES = frozenset(
    {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "iscan.run_id",
        "iscan.stage",
        "iscan.job_kind",
        "iscan.job_attempt",
        "iscan.provider",
        "iscan.provider_config",
        "iscan.model_id",
        "iscan.role",
        "iscan.attempt",
        "iscan.outcome",
        "iscan.status",
        "iscan.dependency",
        "iscan.failure_kind",
        "exception.type",
    }
)
# Fewer than the span ones: a metric attribute must have few values (no run id).
METRIC_ATTRIBUTES = frozenset(
    {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "iscan.stage",
        "iscan.provider",
        "iscan.model_id",
        "iscan.role",
        "iscan.outcome",
        "iscan.status",
        "iscan.token_type",
    }
)
_SAFE_VALUE = re.compile(r"[A-Za-z0-9_.:/{}\-]{1,128}")  # no space, '@', '+', '?', '='

# The names of the metrics (what the dashboards and alert rules of #53 refer to).
RUNS_STARTED = "iscan.runs.started"
RUNS_FINISHED = "iscan.runs.finished"  # attribute iscan.status = terminal status
STAGE_DURATION = "iscan.run.stage.duration"
LLM_TOKENS = "iscan.llm.tokens"
LLM_COST = "iscan.llm.cost"
LLM_CALLS = "iscan.llm.calls"
HTTP_REQUESTS = "iscan.http.requests"

# Terminal statuses of a run; failed / (all of these) is the profile-run failure rate.
TERMINAL_STATUSES = ("completed", "partial", "insufficient_sources", "stopped", "failed")

Attributes = dict[str, str | int | float | bool]


def _clean(attributes: Mapping[str, Any], allowed: frozenset[str]) -> Attributes:
    clean: Attributes = {}
    for key, value in attributes.items():
        if key not in allowed or value is None:
            continue
        if isinstance(value, bool | int | float):
            clean[key] = value
        elif _SAFE_VALUE.fullmatch(str(value)):
            clean[key] = str(value)
    return clean


def span_attributes(attributes: Mapping[str, Any]) -> Attributes:
    return _clean(attributes, SPAN_ATTRIBUTES)


def metric_attributes(attributes: Mapping[str, Any]) -> Attributes:
    return _clean(attributes, METRIC_ATTRIBUTES)


def failure_rate(finished_by_status: Mapping[str, int | float]) -> float | None:
    """The profile-run failure rate: failed runs divided by finished runs (any terminal status)
    over a window. None when no run finished in the window (no rate, no alert). The same quantity
    as the query in the README: failed / total of `iscan.runs.finished`."""
    total = sum(finished_by_status.get(status, 0) for status in TERMINAL_STATUSES)
    if total == 0:
        return None
    return finished_by_status.get("failed", 0) / total


@dataclass(frozen=True)
class Exporters:
    span_processors: Sequence[SpanProcessor] = ()
    metric_readers: Sequence[MetricReader] = ()


class Telemetry:
    def __init__(self, service: str, exporters: Exporters | None = None) -> None:
        exporters = exporters or Exporters()
        self.service = service
        resource = Resource.create({"service.name": service})
        self.tracer_provider = TracerProvider(resource=resource)
        for processor in exporters.span_processors:
            self.tracer_provider.add_span_processor(processor)
        self.meter_provider = MeterProvider(
            resource=resource, metric_readers=list(exporters.metric_readers)
        )
        self.tracer = self.tracer_provider.get_tracer(INSTRUMENTATION_NAME)
        meter = self.meter_provider.get_meter(INSTRUMENTATION_NAME)
        self._runs_started = meter.create_counter(RUNS_STARTED, unit="{run}")
        self._runs_finished = meter.create_counter(RUNS_FINISHED, unit="{run}")
        self._stage_duration = meter.create_histogram(STAGE_DURATION, unit="s")
        self._tokens = meter.create_counter(LLM_TOKENS, unit="{token}")
        self._cost = meter.create_counter(LLM_COST, unit="EUR")
        self._calls = meter.create_counter(LLM_CALLS, unit="{call}")
        self._http = meter.create_counter(HTTP_REQUESTS, unit="{request}")

    def shutdown(self) -> None:
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()

    # ---- spans ----

    @contextmanager
    def span(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        parent: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
    ) -> Iterator[Span]:
        """A span that is current inside the block. An exception that leaves the block is recorded
        as an event with its type only, marks the span as an error, and goes on."""
        with self.tracer.start_as_current_span(
            name,
            context=parent,
            kind=kind,
            attributes=span_attributes(attributes or {}),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except BaseException as error:
                mark_failed(span, type(error).__name__)
                raise

    # ---- metrics ----

    def run_started(self) -> None:
        self._runs_started.add(1)

    def run_finished(self, status: str) -> None:
        self._runs_finished.add(1, metric_attributes({"iscan.status": status}))

    def stage_duration(self, stage: str, seconds: float, outcome: str) -> None:
        self._stage_duration.record(
            seconds, metric_attributes({"iscan.stage": stage, "iscan.outcome": outcome})
        )

    def llm_call(
        self,
        provider: str,
        model_id: str,
        role: str,
        outcome: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        cost_eur: float,
    ) -> None:
        base = {"iscan.provider": provider, "iscan.model_id": model_id, "iscan.role": role}
        self._calls.add(1, metric_attributes({**base, "iscan.outcome": outcome}))
        for token_type, count in (
            ("input", input_tokens),
            ("output", output_tokens),
            ("reasoning", reasoning_tokens),
        ):
            if count:
                self._tokens.add(count, metric_attributes({**base, "iscan.token_type": token_type}))
        if cost_eur:
            self._cost.add(cost_eur, metric_attributes(base))

    def http_request(self, method: str, route: str, status: int) -> None:
        self._http.add(
            1,
            metric_attributes(
                {
                    "http.request.method": method,
                    "http.route": route,
                    "http.response.status_code": status,
                }
            ),
        )


def mark_failed(span: Span, error_type: str, attributes: Mapping[str, Any] | None = None) -> None:
    """A span event and an error status, with the error type and allow-listed attributes only."""
    span.add_event(
        "failure",
        span_attributes({"exception.type": error_type, **(attributes or {})}),
    )
    span.set_status(Status(StatusCode.ERROR))


# ---- the process-wide instance ----

# Before `configure`: spans and metrics exist, nothing is exported.
_current = Telemetry("supplier-iscan")


def current() -> Telemetry:
    return _current


def install(telemetry: Telemetry) -> Telemetry:
    """Replace the process-wide instance; returns the previous one (tests put it back)."""
    global _current
    previous, _current = _current, telemetry
    return previous


def span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    parent: Context | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Any:
    return _current.span(name, attributes, parent, kind)


def record_failure(error_type: str, attributes: Mapping[str, Any] | None = None) -> None:
    """A failure that was handled (a provider error, a run that fails or pauses): an event on the
    current span, so that it is linked to the run's trace."""
    current_span = trace.get_current_span()
    if current_span.get_span_context().is_valid:
        mark_failed(current_span, error_type, attributes)


@contextmanager
def stage_span(stage: str, run_id: object) -> Iterator[Span]:
    """A stage of a run: a span and the stage duration metric."""
    started = time.monotonic()
    outcome = "ok"
    with _current.span("run.stage", {"iscan.stage": stage, "iscan.run_id": str(run_id)}) as s:
        try:
            yield s
        except BaseException:
            outcome = "error"
            raise
        finally:
            _current.stage_duration(stage, time.monotonic() - started, outcome)


# ---- propagation through the queue ----

_PROPAGATOR = TraceContextTextMapPropagator()


def current_traceparent() -> str | None:
    """The W3C `traceparent` of the current span, to store with a queued job."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get(TRACEPARENT)


def context_from_traceparent(traceparent: object) -> Context | None:
    """The context to continue, or None when the job has none (or a malformed one)."""
    if not isinstance(traceparent, str):
        return None
    extracted = _PROPAGATOR.extract({TRACEPARENT: traceparent}, otel_context.Context())
    if not trace.get_current_span(extracted).get_span_context().is_valid:
        return None
    return extracted

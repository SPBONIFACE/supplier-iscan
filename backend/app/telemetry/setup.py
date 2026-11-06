"""Start telemetry for a process (`api` or `worker`) from the settings (#51)."""

import logging

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings
from app.telemetry import core
from app.telemetry.logs import configure_logging

logger = logging.getLogger(__name__)

EXPORT_INTERVAL_MILLIS = 15_000
MAX_QUEUE_SIZE = 512  # spans waiting for export; beyond it spans are dropped, never awaited


def build_telemetry(service: str, settings: Settings) -> core.Telemetry:
    """Without an endpoint: spans and metrics exist, nothing is exported. With one: OTLP over
    HTTP from background threads, each export abandoned after the configured timeout."""
    endpoint = settings.telemetry_endpoint
    if endpoint is None:
        return core.Telemetry(service)
    timeout = settings.telemetry_export_timeout_seconds
    span_exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=timeout)
    metric_exporter = OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=timeout)
    return core.Telemetry(
        service,
        core.Exporters(
            span_processors=[
                BatchSpanProcessor(
                    span_exporter,
                    max_queue_size=MAX_QUEUE_SIZE,
                    export_timeout_millis=timeout * 1000,
                )
            ],
            metric_readers=[
                PeriodicExportingMetricReader(
                    metric_exporter,
                    export_interval_millis=EXPORT_INTERVAL_MILLIS,
                    export_timeout_millis=timeout * 1000,
                )
            ],
        ),
    )


def configure(service: str, settings: Settings) -> core.Telemetry:
    """JSON logs, and the process-wide telemetry. Called once at the start of the API and of the
    worker. Only the fact that export is on is logged, never the address."""
    configure_logging(service)
    telemetry = build_telemetry(service, settings)
    core.install(telemetry)
    logger.info(
        "Telemetry export is %s", "on" if settings.telemetry_endpoint is not None else "off"
    )
    return telemetry

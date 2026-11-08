"""A recording telemetry for the tests: spans, metrics and logs kept in memory."""

import io
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.telemetry import core
from app.telemetry.logs import _HANDLER_NAME, configure_logging


@dataclass
class Recording:
    exporter: InMemorySpanExporter
    reader: InMemoryMetricReader
    stream: io.StringIO = field(default_factory=io.StringIO)

    def spans(self) -> list[ReadableSpan]:
        return list(self.exporter.get_finished_spans())

    def logs(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stream.getvalue().splitlines() if line.strip()]

    def points(self, name: str) -> list[Any]:
        data = self.reader.get_metrics_data()
        found: list[Any] = []
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name == name:
                        found.extend(metric.data.data_points)
        return found

    def finished_by_status(self) -> dict[str, int]:
        return {
            str(point.attributes["iscan.status"]): int(point.value)
            for point in self.points(core.RUNS_FINISHED)
        }

    def everything(self) -> str:
        """All that left the process: spans (events and attributes), metrics, logs."""
        data = self.reader.get_metrics_data()
        parts = [span.to_json() for span in self.spans()]
        parts.append(data.to_json() if data else "")
        parts.append(self.stream.getvalue())
        return "\n".join(parts)


@pytest.fixture
def recording() -> Iterator[Recording]:
    recording = Recording(InMemorySpanExporter(), InMemoryMetricReader())
    previous = core.install(
        core.Telemetry(
            "test",
            core.Exporters([SimpleSpanProcessor(recording.exporter)], [recording.reader]),
        )
    )
    configure_logging("test", recording.stream)
    yield recording
    core.install(previous)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)

"""The request span (#51): a small ASGI middleware, instead of the FastAPI auto-instrumentation,
which records the raw URL (a path can hold an invitation token).

It sets the method, the route template (`/runs/{id}`, never the path itself), and the status, and
nothing else. A trace is started for every request; a `traceparent` header sent by a caller is
ignored, so that nobody outside chooses the trace ids. A failure (an exception, or a 5xx answer)
gives a log entry and a span event in the request's trace.
"""

import logging

from opentelemetry.trace import Span, SpanKind
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.telemetry import core

logger = logging.getLogger(__name__)

UNMATCHED = "unmatched"


class TelemetryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope["method"]
        status = 0

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        telemetry = core.current()
        with telemetry.span(
            f"{method} request", {"http.request.method": method}, kind=SpanKind.SERVER
        ) as span:
            try:
                await self.app(scope, receive, send_with_status)
            except BaseException as error:
                status = status or 500
                self._finish(telemetry, span, scope, method, status)
                logger.error("%s %s failed: %s", method, self._route(scope), type(error).__name__)
                raise
            self._finish(telemetry, span, scope, method, status)
            if status >= 500:
                core.mark_failed(span, "HTTPError", {"http.response.status_code": status})
                logger.warning("%s %s answered %s", method, self._route(scope), status)

    @staticmethod
    def _route(scope: Scope) -> str:
        route = scope.get("route")
        path = getattr(route, "path", None)
        return path if isinstance(path, str) else UNMATCHED

    def _finish(
        self,
        telemetry: core.Telemetry,
        span: Span,
        scope: Scope,
        method: str,
        status: int,
    ) -> None:
        route = self._route(scope)
        span.update_name(f"{method} {route}")
        attributes = core.span_attributes(
            {"http.route": route, "http.response.status_code": status}
        )
        span.set_attributes(attributes)
        telemetry.http_request(method, route, status)

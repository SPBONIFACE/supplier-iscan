"""Demo mode is read-only on the server, not only in the interface (#50, spec Security model).

Every request to `/demo` or below with a method other than GET answers 403, before routing,
authentication or any other check, whether the path exists or not. Together with the demo routes
(GET only, a read-only database transaction, no provider, no queue), a demo visitor cannot write,
queue a job, call a model or crawl.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

DEMO_PREFIX = "/demo"
READ_ONLY = "The demo is read-only."


def is_demo_path(path: str) -> bool:
    return path == DEMO_PREFIX or path.startswith(DEMO_PREFIX + "/")


class DemoReadOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] != "GET"
            and is_demo_path(scope["path"].rstrip("/") or "/")
        ):
            response = JSONResponse({"detail": READ_ONLY}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

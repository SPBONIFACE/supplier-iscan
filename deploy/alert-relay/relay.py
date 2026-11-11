"""Alert relay (#53): a Cloud Monitoring webhook in, a GitHub `workflow_dispatch` of oncall.yml out.

Cloud Monitoring webhooks send a fixed JSON payload with HTTP basic auth and cannot send the
`Authorization: Bearer` header the GitHub API needs, hence this small service. Standard library
only.

    POST /   Cloud Monitoring incident notification (schema version 1.2)
      401    missing or wrong credentials (compared in constant time); nothing is triggered
      400    body over MAX_BODY_BYTES, not JSON, or not the shape of a notification
      202    closed incident: accepted, nothing is triggered
      204    open incident: oncall.yml dispatched on main
      502    GitHub refused or did not answer (an expired token shows here, in the relay's log)

Settings (environment; secrets by name, their values never logged):
    WEBHOOK_USERNAME        user name of the webhook channel (not secret, default
                            "cloud-monitoring")
    WEBHOOK_PASSWORD        password of the webhook channel
                            (Secret Manager: iscan-dev-alert-webhook-token)
    GITHUB_DISPATCH_TOKEN   fine-grained token, Actions: write on this repository only
                            (Secret Manager: iscan-dev-github-dispatch-token)
    GITHUB_REPOSITORY       owner/name of the repository
    ONCALL_ENVIRONMENT      the environment named in the dispatch (default "dev")
    ONCALL_WORKFLOW         the workflow file (default "oncall.yml")
    PORT                    set by Cloud Run

Neither the request body nor a credential is ever written to the log: one line per request with the
status only, and the GitHub status code when a dispatch fails.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY_BYTES = 64 * 1024
GITHUB_API = "https://api.github.com"
DISPATCH_TIMEOUT_SECONDS = 10
# What a dispatch input may hold. Anything else is refused (400), so that nothing unexpected reaches
# the workflow, which treats every input as data anyway.
INCIDENT_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
POLICY_NAME = re.compile(r"[A-Za-z0-9 ._:()/-]{1,128}")
CONSOLE_URL = re.compile(
    r"https://console\.cloud\.google\.com/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,900}"
)

logger = logging.getLogger("alert-relay")

Dispatcher = Callable[[Mapping[str, str]], int]


@dataclass(frozen=True)
class Config:
    username: str
    password: str
    repository: str
    token: str
    environment: str = "dev"
    workflow: str = "oncall.yml"


@dataclass(frozen=True)
class Outcome:
    status: int
    note: str  # for the log line; never holds request content


def load_config(env: Mapping[str, str]) -> Config:
    missing = [
        name
        for name in ("WEBHOOK_PASSWORD", "GITHUB_DISPATCH_TOKEN", "GITHUB_REPOSITORY")
        if not env.get(name, "").strip()
    ]
    if missing:
        raise SystemExit(f"alert-relay: missing settings: {', '.join(missing)}")
    return Config(
        username=env.get("WEBHOOK_USERNAME", "").strip() or "cloud-monitoring",
        password=env["WEBHOOK_PASSWORD"].strip(),
        repository=env["GITHUB_REPOSITORY"].strip(),
        token=env["GITHUB_DISPATCH_TOKEN"].strip(),
        environment=env.get("ONCALL_ENVIRONMENT", "").strip() or "dev",
        workflow=env.get("ONCALL_WORKFLOW", "").strip() or "oncall.yml",
    )


def authorised(header: str | None, config: Config) -> bool:
    """HTTP basic auth, both parts compared in constant time."""
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    user_ok = hmac.compare_digest(username.encode(), config.username.encode())
    password_ok = hmac.compare_digest(password.encode(), config.password.encode())
    return bool(separator) and user_ok and password_ok


def dispatch_inputs(payload: Any, environment: str) -> dict[str, str] | None:
    """The five workflow inputs of an open incident; None when the payload has the wrong shape."""
    if not isinstance(payload, dict) or not isinstance(payload.get("incident"), dict):
        return None
    incident = payload["incident"]
    incident_id = incident.get("incident_id")
    policy_name = incident.get("policy_name")
    url = incident.get("url")
    started_at = incident.get("started_at")
    if not (isinstance(incident_id, str) and INCIDENT_ID.fullmatch(incident_id)):
        return None
    if not (isinstance(policy_name, str) and POLICY_NAME.fullmatch(policy_name)):
        return None
    if not (isinstance(url, str) and CONSOLE_URL.fullmatch(url)):
        return None
    if isinstance(started_at, bool) or not isinstance(started_at, int) or started_at <= 0:
        return None
    try:
        start = datetime.fromtimestamp(started_at, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return {
        "incident_id": incident_id,
        "policy_name": policy_name,
        "environment": environment,
        "started_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "console_url": url,
    }


def handle(
    authorization: str | None,
    content_length: str | None,
    read_body: Callable[[int], bytes],
    config: Config,
    dispatch: Dispatcher,
) -> Outcome:
    """Decide what one POST does. The body is read only after the credentials pass, and never more
    than MAX_BODY_BYTES."""
    if not authorised(authorization, config):
        return Outcome(401, "unauthorised")
    try:
        length = int(content_length or "")
    except ValueError:
        return Outcome(400, "no length")
    if length <= 0 or length > MAX_BODY_BYTES:
        return Outcome(400, "size")
    try:
        payload = json.loads(read_body(length))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        # RecursionError: deeply nested JSON (e.g. 60,000 "[") under the size cap.
        return Outcome(400, "not json")
    if not isinstance(payload, dict) or not isinstance(payload.get("incident"), dict):
        return Outcome(400, "shape")
    state = payload["incident"].get("state")
    if state == "closed":
        return Outcome(202, "closed incident: nothing triggered")
    if state != "open":
        return Outcome(400, "shape")
    inputs = dispatch_inputs(payload, config.environment)
    if inputs is None:
        return Outcome(400, "shape")
    github_status = dispatch(inputs)
    if github_status == 204:
        return Outcome(204, "dispatched")
    return Outcome(502, f"GitHub answered {github_status}")


def github_dispatcher(config: Config) -> Dispatcher:
    url = f"{GITHUB_API}/repos/{config.repository}/actions/workflows/{config.workflow}/dispatches"

    def dispatch(inputs: Mapping[str, str]) -> int:
        body = json.dumps({"ref": "main", "inputs": dict(inputs)}).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed https address
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {config.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "iscan-alert-relay",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=DISPATCH_TIMEOUT_SECONDS) as response:  # noqa: S310
                return int(response.status)
        except urllib.error.HTTPError as error:
            return int(error.code)
        except (urllib.error.URLError, TimeoutError):
            return 0

    return dispatch


def make_handler(config: Config, dispatch: Dispatcher) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "alert-relay"
        sys_version = ""

        def do_POST(self) -> None:  # noqa: N802 - the http.server name
            outcome = handle(
                self.headers.get("Authorization"),
                self.headers.get("Content-Length"),
                self.rfile.read,
                config,
                dispatch,
            )
            self.send_response(outcome.status)
            if outcome.status == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="alert-relay"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            level = logging.ERROR if outcome.status >= 500 else logging.INFO
            logger.log(level, "POST %s %s", outcome.status, outcome.note)

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # the default access log is replaced by the line in do_POST

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    config = load_config(os.environ)
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("", port), make_handler(config, github_dispatcher(config)))  # noqa: S104
    logger.info("alert relay listening on port %s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()

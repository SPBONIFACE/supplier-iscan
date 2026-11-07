"""Check the built frontend image as the gateway to the API (#52). Standard library and Docker only.

    python3 deploy/check_proxy.py IMAGE

Starts a stub "API" (the same image's nginx, answering with what it received) and the frontend image
pointed at it with API_UPSTREAM_URL, on a throwaway Docker network. Then checks that:
  - `/` and a client-side route serve the application;
  - `/api/health?...` reaches the stub as `/health`, with the query string, the cookie, the
    upstream host and the forwarded headers;
  - a POST body is passed on and a body over the limit is refused;
  - the access log has the path, never the query string, a cookie or an invitation token;
  - bad API_UPSTREAM_URL values stop the container.
No secret is used; the marker values below are made up.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

STUB_FIELDS = {
    "path": "$uri",
    "args": "$args",
    "host": "$http_host",
    "xff": "$http_x_forwarded_for",
    "proto": "$http_x_forwarded_proto",
    "cookie": "$http_cookie",
    "method": "$request_method",
}
# The stub answers every request with what the "API" received.
STUB_CONF = (
    "server { listen 8080; location / { default_type text/plain; return 200 "
    + '"'
    + "|".join(f"{name}={value}" for name, value in STUB_FIELDS.items())
    + '"; } }'
)
MARK_QUERY = "marker_query_12345"
MARK_COOKIE = "marker_cookie_67890"
MARK_INVITE = "marker_invite_abcde"


class Failure(Exception):
    pass


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if check and result.returncode != 0:
        raise Failure(f"docker {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result


def get(
    url: str, *, method: str = "GET", data: bytes | None = None, cookie: str | None = None
) -> tuple[int, str]:
    request = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    if cookie:
        request.add_header("Cookie", cookie)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)
    print(f"ok: {message}")


def wait_for(url: str) -> None:
    for _ in range(40):
        try:
            get(url)
            return
        except OSError:
            time.sleep(0.5)
    raise Failure(f"nothing answered at {url}")


def check(image: str) -> None:
    suffix = uuid.uuid4().hex[:8]
    network, stub, web = f"iscan-proxy-{suffix}", f"iscan-stub-{suffix}", f"iscan-web-{suffix}"
    with tempfile.TemporaryDirectory() as tmp:
        conf = Path(tmp) / "stub.conf"
        conf.write_text(STUB_CONF)
        conf.chmod(0o644)
        docker("network", "create", network)
        try:
            docker(
                "run", "--detach", "--name", stub, "--network", network,
                "--entrypoint", "nginx", "-v", f"{conf}:/etc/nginx/conf.d/default.conf:ro",
                image, "-g", "daemon off;",
            )  # fmt: skip
            docker(
                "run", "--detach", "--name", web, "--network", network,
                "--publish", "127.0.0.1::8080",
                "-e", f"API_UPSTREAM_URL=http://{stub}:8080", "-e", "API_UPSTREAM_ALLOW_HTTP=1",
                image,
            )  # fmt: skip
            port = docker("port", web, "8080/tcp").stdout.split(":")[-1].strip()
            base = f"http://127.0.0.1:{port}"
            wait_for(f"{base}/")

            status, body = get(f"{base}/")
            expect(status == 200 and 'id="root"' in body, "/ serves the application")
            status, body = get(f"{base}/runs/abc")
            expect(
                status == 200 and 'id="root"' in body, "a client-side route serves the application"
            )

            query = f"q={MARK_QUERY}"
            status, body = get(f"{base}/api/health?{query}", cookie=f"session={MARK_COOKIE}")
            fields = dict(part.split("=", 1) for part in body.split("|"))
            expect(status == 200, "/api/health is forwarded and answered")
            expect(fields["path"] == "/health", "the /api prefix is removed")
            expect(fields["args"] == query, "the query string reaches the API")
            expect(fields["cookie"] == f"session={MARK_COOKIE}", "the cookie reaches the API")
            expect(fields["host"] == f"{stub}:8080", "Host is the upstream's own")
            expect(bool(fields["xff"]), "X-Forwarded-For is passed")
            expect(fields["proto"] == "http", "X-Forwarded-Proto is passed")

            status, body = get(f"{base}/api/invitations/{MARK_INVITE}", method="GET")
            expect(
                status == 200 and f"path=/invitations/{MARK_INVITE}" in body,
                "a path with a token is forwarded",
            )

            status, body = get(f"{base}/api/runs", method="POST", data=b'{"a": 1}')
            expect(status == 200 and "method=POST" in body, "a POST is forwarded")
            status, _ = get(f"{base}/api/runs", method="POST", data=b"x" * (300 * 1024))
            expect(status == 413, "a body over the limit is refused")

            logs = docker("logs", web)
            log = logs.stdout + logs.stderr
            expect("/api/health" in log, "the access log has the path")
            for secret, what in (
                (MARK_QUERY, "query string"),
                (MARK_COOKIE, "cookie"),
                (MARK_INVITE, "invitation token"),
            ):
                expect(secret not in log, f"the logs hold no {what}")
        finally:
            docker("rm", "--force", web, stub, check=False)
            docker("network", "rm", network, check=False)

    for bad in (
        "",
        "javascript:alert(1)",
        "http://example.test",
        "https://x.test/path",
        "https://x.test;evil",
    ):
        result = docker("run", "--rm", "-e", f"API_UPSTREAM_URL={bad}", image, check=False)
        expect(result.returncode != 0, f"API_UPSTREAM_URL={bad!r} stops the container")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        check(argv[1])
    except Failure as failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(json.dumps({"result": "pass"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""The access log under real uvicorn (#51 QA): route template, status and duration; never the path
or the query string, which can hold an e-mail address or a token."""

import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from app.telemetry.logs import configure_logging
from tests.support import make_client
from tests.telemetry.conftest import Recording


def test_the_access_log_has_the_route_template_and_never_the_path_or_query(
    recording: Recording,
) -> None:
    app = make_client(database_check=lambda: True).app
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    config = uvicorn.Config(app, log_config=uvicorn.config.LOGGING_CONFIG)
    configure_logging("test", recording.stream)  # as at import of app.main, after uvicorn's set-up
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        for path in (
            "/health?token=QSENT-TOKEN-abc&email=zoe.o%27brien%40q-mail.example",
            "/invitations/QSENT-INVITE?email=a%40b.example",
            "/QSENT-PATH-zoe@q-mail.example/phone-0198765432?pw=QSENT-QPW",
        ):
            try:
                urllib.request.urlopen(base + path, timeout=5).read()  # noqa: S310
            except urllib.error.HTTPError:
                pass
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()

    written = recording.stream.getvalue()
    for leaked in ("QSENT", "q-mail", "0198765432", "token=", "email="):
        assert leaked not in written
    messages = [entry["message"] for entry in recording.logs()]
    assert any(m.startswith("GET /health 200") for m in messages)
    assert any(m.startswith("GET /invitations/{token} ") for m in messages)
    assert any(m.startswith("GET unmatched 404") for m in messages)
    assert all(entry["logger"] != "uvicorn.access" for entry in recording.logs())
    for span in recording.spans():
        assert not set(span.attributes or {}) & {"http.target", "url.full", "http.url", "url.query"}

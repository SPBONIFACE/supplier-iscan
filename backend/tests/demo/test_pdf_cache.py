"""The anonymous demo card PDF is cached and its concurrency limited (#50, QA)."""

import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine

from app.config import Settings
from app.demo import pdf_cache
from tests.demo.support import build, finished_run
from tests.support import make_client


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    pdf_cache.clear()
    yield
    pdf_cache.clear()


class FakeRender:
    """Stands for the PDF generator (which needs Pango): counts calls and can be held."""

    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.hold = False

    def __call__(self, card: Any) -> bytes:
        self.calls += 1
        self.started.set()
        if self.hold:
            assert self.release.wait(10)
        return b"%PDF-fake-" + str(self.calls).encode()


def test_a_second_request_for_the_same_profile_and_language_is_served_from_memory(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = FakeRender()
    monkeypatch.setattr("app.demo.routes.render_pdf", render)
    demo = finished_run(engine, settings)
    profile = build(engine, demo)[0]
    client = make_client(settings=demo.settings, engine=engine)

    first = client.get(f"/demo/profiles/{profile.id}/pdf")
    second = client.get(f"/demo/profiles/{profile.id}/pdf")
    french = client.get(f"/demo/profiles/{profile.id}/pdf?lang=fr")

    assert (first.status_code, second.status_code, french.status_code) == (200, 200, 200)
    assert first.content == second.content and french.content != first.content
    assert render.calls == 2  # one per language
    assert "attachment" in second.headers["content-disposition"]


def test_replacing_the_demo_set_never_serves_a_stale_file(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = FakeRender()
    monkeypatch.setattr("app.demo.routes.render_pdf", render)
    demo = finished_run(engine, settings)
    old = build(engine, demo)[0]
    client = make_client(settings=demo.settings, engine=engine)
    assert client.get(f"/demo/profiles/{old.id}/pdf").status_code == 200

    # The command replaces the set; this process's cache still holds a file for the old id.
    pdf_cache._cache[(old.id, "en")] = b"%PDF-stale"
    new = build(engine, demo)[0]

    assert client.get(f"/demo/profiles/{old.id}/pdf").status_code == 404  # the old id is gone
    fresh = client.get(f"/demo/profiles/{new.id}/pdf")
    assert fresh.status_code == 200 and b"stale" not in fresh.content
    assert (old.id, "en") not in pdf_cache._cache  # the command in this process clears it


def test_the_cache_is_bounded() -> None:
    for _ in range(pdf_cache.MAX_CACHED + 10):
        pdf_cache.cached_pdf(uuid.uuid4(), "en", lambda: b"x")

    assert len(pdf_cache._cache) == pdf_cache.MAX_CACHED


def test_concurrent_renders_are_capped_and_the_rest_told_to_retry(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = FakeRender()
    render.hold = True
    monkeypatch.setattr("app.demo.routes.render_pdf", render)
    monkeypatch.setattr(pdf_cache, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(pdf_cache, "WAIT_SECONDS", 0.3)
    demo = finished_run(engine, settings)
    profile = build(engine, demo)[0]
    client = make_client(settings=demo.settings, engine=engine)
    assert client.get("/demo/profiles").status_code == 200

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(client.get, f"/demo/profiles/{profile.id}/pdf?lang=en")
        assert render.started.wait(10)
        busy = client.get(f"/demo/profiles/{profile.id}/pdf?lang=fr")  # another file, no place
        listing = client.get("/demo/profiles")  # the rest of the demo still answers
        render.release.set()
        assert holder.result(timeout=15).status_code == 200

    assert busy.status_code == 503
    assert busy.headers["retry-after"] == str(pdf_cache.RETRY_AFTER_SECONDS)
    assert busy.json() == {"detail": pdf_cache.BUSY}
    assert listing.status_code == 200
    assert render.calls == 1  # the refused request rendered nothing


def test_a_cached_file_needs_no_render_place(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = FakeRender()
    monkeypatch.setattr("app.demo.routes.render_pdf", render)
    demo = finished_run(engine, settings)
    profile = build(engine, demo)[0]
    client = make_client(settings=demo.settings, engine=engine)
    assert client.get(f"/demo/profiles/{profile.id}/pdf").status_code == 200
    taken = threading.BoundedSemaphore(1)
    taken.acquire()  # every place is in use
    monkeypatch.setattr(pdf_cache, "_slots", taken)
    monkeypatch.setattr(pdf_cache, "WAIT_SECONDS", 0.1)

    assert client.get(f"/demo/profiles/{profile.id}/pdf").status_code == 200

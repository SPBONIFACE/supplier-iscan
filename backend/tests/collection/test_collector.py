"""#18: the collector on synthetic fixture sites (mock transport, no network, no personal data)."""

import logging

import httpx2
import pytest

from app.collection.settings import CollectionSettings
from tests.collection.support import (
    HOST,
    chunks,
    html,
    make_collector,
    pdf_bytes,
    pdf_response,
    urlset,
    xml,
)

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"


def site_pages() -> dict[tuple[str, str], httpx2.Response]:
    return {
        (HOST, "/"): html(
            "<nav><a href='/menu-only'>x</a></nav><h1>Welcome to Acme Supplies</h1>"
            "<a href='/about'>About</a><a href='/nachhaltigkeit'>Nachhaltigkeit</a>"
            "<a href='/reports/esg-2025.pdf'>ESG report</a><a href='https://other.example/z'>z</a>"
        ),
        (HOST, "/about"): html("<p>Acme Supplies SA makes bolts.</p>"),
        (HOST, "/nachhaltigkeit"): html("<p>Wir sind nachhaltig.</p>"),
        (HOST, "/qualite"): html("<p>Certifiée ISO 9001.</p>"),
        (HOST, "/sites"): html("<p>Lyon et Berlin.</p>"),
        (HOST, "/sitemap.xml"): xml(
            f"<sitemapindex><sitemap><loc>https://{HOST}/sm1.xml</loc></sitemap></sitemapindex>"
        ),
        (HOST, "/sm1.xml"): xml(urlset("/qualite", "/sites", "/blog/1"), gz=False),
        (HOST, "/reports/esg-2025.pdf"): pdf_response(pdf_bytes("ESG report of Acme Supplies SA")),
    }


def urls(stored: list) -> list[str]:  # type: ignore[type-arg]
    return [record.url for record in stored]


def test_pages_come_from_links_and_sitemap_indexes_and_pdfs_are_collected() -> None:
    collector, _site, stored, _sleeps, _ = make_collector(site_pages())

    result = collector.collect(SITE, NAME)

    assert set(urls(stored)) == {
        SITE,
        f"https://{HOST}/about",
        f"https://{HOST}/nachhaltigkeit",
        f"https://{HOST}/qualite",  # only in the sitemap index's child
        f"https://{HOST}/sites",
        f"https://{HOST}/reports/esg-2025.pdf",
    }
    home = stored[0]
    assert home.content_type == "text/html" and "Welcome to Acme" in home.text
    assert "Menu" not in home.text and "menu-only" not in urls(stored)
    pdf = next(r for r in stored if r.url.endswith(".pdf"))
    assert pdf.content_type == "application/pdf"
    assert "ESG report" in pdf.text and pdf.author == "A. Writer"
    assert pdf.fetched_at.tzinfo is not None
    assert not result.identity_to_verify


def test_the_number_of_pages_per_run_is_capped() -> None:
    settings = CollectionSettings(
        max_pages=3, reserved_independent=0, min_delay_seconds=0, backoff_seconds=0
    )
    collector, _site, stored, _s, _ = make_collector(site_pages(), settings)

    collector.collect(SITE, NAME)

    pages = [r for r in stored if r.content_type == "text/html"]
    assert len(pages) == 3 and pages[0].url == SITE


def test_a_pdf_over_the_limit_is_skipped_logged_and_not_downloaded_beyond_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    pulled: list[int] = []
    pages = site_pages()
    pages[(HOST, "/reports/esg-2025.pdf")] = httpx2.Response(
        200,
        content=chunks(10_000_000, 1000, pulled),  # chunked: no Content-Length
        headers={"content-type": "application/pdf"},
    )
    settings = CollectionSettings(max_pdf_bytes=5000, min_delay_seconds=0, backoff_seconds=0)
    collector, _site, stored, _s, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME)

    assert not any(r.url.endswith(".pdf") for r in stored)
    assert sum(pulled) <= 5000 + 2000  # stopped at the limit (one chunk of slack), not 10 MB
    assert any("esg-2025.pdf" in m and "exceeds 5000" in m for m in caplog.messages), (
        caplog.messages
    )


def test_a_lying_content_length_cannot_get_past_the_limit() -> None:
    pages = site_pages()
    pages[(HOST, "/reports/esg-2025.pdf")] = httpx2.Response(
        200,
        content=b"%PDF-" + b"0" * 20_000,
        headers={"content-type": "application/pdf", "content-length": "10"},
    )
    settings = CollectionSettings(max_pdf_bytes=5000, min_delay_seconds=0, backoff_seconds=0)
    collector, _site, stored, _s, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME)

    assert not any(r.url.endswith(".pdf") for r in stored)


def test_an_announced_size_over_the_limit_is_refused_without_reading_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    pulled: list[int] = []
    pages = site_pages()
    pages[(HOST, "/reports/esg-2025.pdf")] = httpx2.Response(
        200,
        content=chunks(50_000, 1000, pulled),
        headers={"content-type": "application/pdf", "content-length": "50000"},
    )
    settings = CollectionSettings(max_pdf_bytes=5000, min_delay_seconds=0, backoff_seconds=0)
    collector, _site, _stored, _s, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME)

    assert pulled == []
    assert any("50000" in m for m in caplog.messages)


def test_malformed_encrypted_and_empty_pdfs_are_skipped_never_a_crash(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    from tests.collection.support import encrypted_pdf

    for content in (b"%PDF-1.7\ngarbage", encrypted_pdf(), pdf_bytes("")):
        pages = site_pages()
        pages[(HOST, "/reports/esg-2025.pdf")] = pdf_response(content)
        collector, _site, stored, _s, _ = make_collector(pages)

        collector.collect(SITE, NAME)

        assert not any(r.url.endswith(".pdf") for r in stored)
        assert len(stored) == 5  # the pages are still collected
    assert any("Empty content" in m and "esg-2025.pdf" in m for m in caplog.messages)


def test_a_page_with_no_text_is_logged_as_empty_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    pages = site_pages()
    pages[(HOST, "/about")] = html("<script>1</script>")
    collector, _site, stored, _s, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    assert f"https://{HOST}/about" not in urls(stored)
    assert any("Empty content" in m and "/about" in m for m in caplog.messages)


def test_french_german_and_cjk_pages_are_stored_in_nfc_without_garbling() -> None:
    pages = {
        (HOST, "/"): html(
            "<a href='/about'>x</a><a href='/standorte'>y</a><a href='/esg'>z</a>",
            "iso-8859-1",
            '<meta charset="iso-8859-1">',
        ),
        (HOST, "/about"): html("<p>Société à Genève</p>", "cp1252", '<meta charset="cp1252">'),
        (HOST, "/standorte"): html("<p>Größe, Qualität</p>"),
        (HOST, "/esg"): html(
            "<p>株式会社 品質管理 北京</p>", "shift_jis", '<meta charset="shift_jis">'
        ),
    }
    collector, _site, stored, _s, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    texts = {r.url.rsplit("/", 1)[1]: r.text for r in stored}
    assert texts["about"] == "Société à Genève"
    assert texts["standorte"] == "Größe, Qualität"
    assert texts["esg"] == "株式会社 品質管理 北京"


def test_a_path_the_permission_check_excludes_is_never_fetched() -> None:
    pages = site_pages()
    pages[(HOST, "/robots.txt")] = httpx2.Response(200, text="User-agent: *\nDisallow: /about\n")
    collector, site, stored, _s, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    assert f"https://{HOST}/about" not in urls(stored)
    assert not any(request.url.endswith("/about") for request in site.seen)


def test_a_domain_that_reserves_text_and_data_mining_is_not_collected() -> None:
    pages = site_pages()
    pages[(HOST, "/.well-known/tdmrep.json")] = httpx2.Response(
        200, text="[]", headers={"tdm-reservation": "1"}
    )
    collector, site, stored, _s, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    assert stored == []
    assert not any(request.url.endswith("/about") for request in site.seen)


def test_requests_wait_the_minimum_delay_and_failed_fetches_retry_with_backoff() -> None:
    calls = {"n": 0}

    def flaky(request: httpx2.Request) -> None:
        if request.url.path == "/about":
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx2.ConnectError("boom")

    settings = CollectionSettings(min_delay_seconds=2.0, backoff_seconds=1.0, retries=2)
    collector, site, stored, sleeps, _ = make_collector(site_pages(), settings)
    site.error = flaky

    collector.collect(SITE, NAME)

    assert f"https://{HOST}/about" in urls(stored) and calls["n"] == 3
    assert 1.0 in sleeps and 2.0 in sleeps  # backoff doubles: 1 s, then 2 s
    assert all(s <= 2.0 for s in sleeps)  # the domain delay never exceeds the configured one


def test_a_server_error_is_retried_then_given_up(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    pages = site_pages()
    pages[(HOST, "/about")] = httpx2.Response(503, headers={"retry-after": "3"})
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0.5, retries=2)
    collector, site, stored, sleeps, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME)

    assert f"https://{HOST}/about" not in urls(stored)
    assert sum(request.url.endswith("/about") for request in site.seen) == 3
    assert 3.0 in sleeps  # Retry-After is honoured
    assert any("Gave up" in m for m in caplog.messages)


def test_the_stop_check_runs_before_every_request() -> None:
    class Stopped(Exception):
        pass

    def check() -> None:
        raise Stopped

    collector, site, _stored, _s, _ = make_collector(site_pages(), check=check)
    with pytest.raises(Stopped):
        collector.collect(SITE, NAME)
    assert site.seen == []


def test_identity_is_flagged_when_the_name_is_on_none_of_the_sources() -> None:
    pages = {
        (HOST, "/"): html("<h1>Welcome</h1><a href='/about'>About</a>"),
        (HOST, "/about"): html("<p>We are a family business founded in 1950.</p>"),
    }
    collector, _site, stored, _s, _ = make_collector(pages)

    result = collector.collect(SITE, NAME)

    assert len(stored) == 2 and result.identity_to_verify


def test_identity_is_not_flagged_when_the_name_appears_normalised() -> None:
    pages = {
        (HOST, "/"): html("<h1>Welcome</h1><a href='/about'>About</a>"),
        (HOST, "/about"): html("<p>ACME  SUPPLIES, Inc. is based in Lyon.</p>"),
    }
    collector, _site, _stored, _s, _ = make_collector(pages)

    assert not collector.collect(SITE, NAME).identity_to_verify


def test_the_name_in_a_pdf_alone_counts() -> None:
    pages = {
        (HOST, "/"): html("<h1>Welcome</h1><a href='/r.pdf'>report</a>"),
        (HOST, "/r.pdf"): pdf_response(pdf_bytes("Annual report of Acme Supplies")),
    }
    collector, _site, _stored, _s, _ = make_collector(pages)

    assert not collector.collect(SITE, NAME).identity_to_verify

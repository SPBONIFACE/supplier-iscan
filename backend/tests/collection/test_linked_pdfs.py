"""#138: PDFs hosted on independent pages found by retrieval are followed, financial ones first."""

from urllib.parse import urlsplit

import httpx2

from app.collection.collector import _is_financial
from app.collection.settings import CollectionSettings, load_collection_settings
from app.collection.source_store import SourceRecord
from app.extraction.source_type import classify_source
from tests.collection.support import HOST, OTHER, html, make_collector, pdf_bytes, pdf_response
from tests.http_client.support import MockSite

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"
PAGE = f"https://{OTHER}/entry"
FAR = "far.example"
Pages = dict[tuple[str, str], httpx2.Response]


def register(*links: tuple[str, str]) -> httpx2.Response:
    body = "<p>Register entry of Acme Supplies SA</p>" + "".join(
        f"<a href='{href}'>{anchor}</a>" for href, anchor in links
    )
    return html(body)


def pdf(text: str) -> httpx2.Response:
    return pdf_response(pdf_bytes(text))


def run(
    pages: Pages, settings: CollectionSettings | None = None, url: str = PAGE
) -> tuple[list[str], list[SourceRecord], list[str]]:
    """The addresses requested, the sources stored, the addresses skipped."""
    collector, site, stored, _sleeps, _ = make_collector(pages, settings)
    result = collector.collect(SITE, NAME, lambda _lacking: [url])
    return requested(site), stored, result.skipped


def requested(site: MockSite) -> list[str]:
    return [f"https://{s.host_header}{urlsplit(s.url).path}" for s in site.seen]


def stored_pdfs(stored: list[SourceRecord]) -> list[str]:
    return [r.url for r in stored if r.url.endswith(".pdf")]


def test_the_financial_pdf_is_fetched_first_and_another_host_never() -> None:
    pages: Pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/entry"): register(
            ("/docs/brochure.pdf", "Brochure"),
            ("/docs/a.pdf", "Annual accounts 2025"),
            (f"https://{FAR}/x.pdf", "Jahresabschluss"),
        ),
        (OTHER, "/docs/brochure.pdf"): pdf("Brochure"),
        (OTHER, "/docs/a.pdf"): pdf("Revenue and total assets"),
    }

    urls, stored, _skipped = run(pages)

    assert [u for u in urls if u.endswith(".pdf")] == [
        f"https://{OTHER}/docs/a.pdf",
        f"https://{OTHER}/docs/brochure.pdf",
    ]
    assert not any(FAR in u for u in urls)
    assert stored_pdfs(stored) == [
        f"https://{OTHER}/docs/a.pdf",
        f"https://{OTHER}/docs/brochure.pdf",
    ]


def test_the_ranking_knows_english_french_german_words_and_the_filed_accounts_name() -> None:
    for url, anchor in [
        ("https://x.example/a.pdf", "Annual Report"),
        ("https://x.example/Jahresabschluss-2025.pdf", ""),
        ("https://x.example/ges%C3%A4ft.pdf", "Geschäftsbericht"),
        ("https://x.example/b.pdf", "Comptes annuels"),
        ("https://x.example/b.pdf", "Rapport annuel"),
        ("https://x.example/b.pdf", "Bilanz"),
        ("https://x.example/b.pdf", "Financial statements"),
        ("https://x.example/files/EA2025.pdf", ""),
        ("https://x.example/files/ea-2024_acme.pdf", ""),
    ]:
        assert _is_financial(url, anchor), (url, anchor)
    for url, anchor in [
        ("https://x.example/brochure.pdf", "Brochure"),
        ("https://x.example/area2025.pdf", ""),
        ("https://x.example/EA25.pdf", ""),
    ]:
        assert not _is_financial(url, anchor), (url, anchor)


def test_at_most_two_pdfs_per_page() -> None:
    names = ["a", "b", "c"]
    pages: Pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/entry"): register(*((f"/{n}.pdf", n) for n in names)),
    }
    pages |= {(OTHER, f"/{n}.pdf"): pdf(f"Doc {n}") for n in names}

    _urls, stored, _skipped = run(pages)

    assert stored_pdfs(stored) == [f"https://{OTHER}/a.pdf", f"https://{OTHER}/b.pdf"]


def test_at_most_the_run_cap_across_pages() -> None:
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_linked_pdfs=3)
    pages: Pages = {(HOST, "/"): html("<p>Acme Supplies SA</p>")}
    entries = []
    for page in ("p1", "p2"):
        pages[(OTHER, f"/{page}")] = register(*((f"/{page}{i}.pdf", "x") for i in range(2)))
        pages |= {(OTHER, f"/{page}{i}.pdf"): pdf(f"Doc {page}{i}") for i in range(2)}
        entries.append(f"https://{OTHER}/{page}")
    collector, _site, stored, _s, _ = make_collector(pages, settings)

    collector.collect(SITE, NAME, lambda _lacking: entries)

    assert len(stored_pdfs(stored)) == 3


def test_the_default_run_cap_is_three_and_has_an_environment_variable() -> None:
    assert CollectionSettings().max_linked_pdfs == 3
    assert load_collection_settings({"COLLECT_MAX_LINKED_PDFS": "1"}).max_linked_pdfs == 1


def test_a_retrieved_page_of_the_suppliers_own_domain_does_not_trigger_the_step() -> None:
    pages: Pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (HOST, "/news"): register(("/files/accounts.pdf", "Accounts")),
        (HOST, "/files/accounts.pdf"): pdf("Accounts"),
    }

    urls, _stored, _skipped = run(pages, url=f"https://{HOST}/news")

    assert not any(u.endswith(".pdf") for u in urls)


def test_a_pdf_already_stored_is_not_fetched_again() -> None:
    pdf_url = f"https://{OTHER}/a.pdf"
    pages: Pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/entry"): register(("/a.pdf", "Accounts")),
        (OTHER, "/entry2"): register(("/a.pdf", "Accounts")),
        (OTHER, "/a.pdf"): pdf("Accounts"),
    }
    collector, site, stored, _s, _ = make_collector(pages)

    collector.collect(SITE, NAME, lambda _lacking: [PAGE, f"https://{OTHER}/entry2"])

    assert requested(site).count(pdf_url) == 1
    assert stored_pdfs(stored) == [pdf_url]


def test_the_pdf_is_linked_from_the_page_and_never_typed_supplier_claim() -> None:
    pages: Pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/entry"): register(("/a.pdf", "Annual accounts")),
        (OTHER, "/a.pdf"): pdf("Accounts"),
    }

    _urls, stored, _skipped = run(pages)

    record = next(r for r in stored if r.url.endswith(".pdf"))
    assert record.linked_from_url == PAGE
    kind = classify_source(record.url, SITE, linked_from_url=record.linked_from_url)
    assert kind == "third_party"


def test_a_failing_or_non_pdf_link_is_skipped_and_the_run_goes_on() -> None:
    pages: Pages = {
        (HOST, "/"): html("<p>Acme Supplies SA</p>"),
        (OTHER, "/entry"): register(
            ("/gone.pdf", "Accounts"), ("/fake.pdf", "Bilanz"), ("/ok.pdf", "other")
        ),
        (OTHER, "/gone.pdf"): httpx2.Response(404),
        (OTHER, "/fake.pdf"): html("<p>not a pdf</p>"),
        (OTHER, "/ok.pdf"): pdf("Fine"),
    }
    settings = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, max_linked_pdfs=5)

    _urls, stored, skipped = run(pages, settings)

    assert f"https://{OTHER}/gone.pdf" in skipped
    assert f"https://{OTHER}/fake.pdf" in skipped
    assert stored_pdfs(stored) == [f"https://{OTHER}/ok.pdf"]

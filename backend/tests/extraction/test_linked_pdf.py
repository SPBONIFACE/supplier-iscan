"""A PDF linked from a page of the supplier's website (#23, owner decision of 27 Oct 2026): the
collector follows it even on another domain and remembers the page, and the storage function
records that page as `Source.linked_from_source_id`."""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.collection.source_store import SourceRecord, store_source
from app.db import Database, utc_now
from app.extraction.source_type import classify_source
from app.models import Source
from tests.collection.support import (
    HOST,
    OTHER,
    SUBDOMAIN,
    html,
    make_collector,
    pdf_bytes,
    pdf_response,
)
from tests.factories import create_organisation
from tests.http_client.support import redirect
from tests.runs_support import create_run

NAME = "Acme Supplies SA"
SITE = f"https://{HOST}/"


def pages() -> dict[tuple[str, str], object]:
    return {
        (HOST, "/"): html(
            "<a href='/about'>About</a>"
            f"<a href='https://{OTHER}/files/acme-profile.pdf'>Company profile</a>"
            f"<a href='https://{OTHER}/other-page'>A page elsewhere</a>"
        ),
        (HOST, "/about"): html("<p>About Acme.</p><a href='/files/local.pdf'>Brochure</a>"),
        (HOST, "/files/local.pdf"): pdf_response(pdf_bytes("Local brochure of Acme")),
        (OTHER, "/files/acme-profile.pdf"): pdf_response(
            pdf_bytes("Profile of Acme hosted elsewhere")
        ),
        (OTHER, "/other-page"): html("<p>Not collected: a page, not a PDF.</p>"),
    }


def test_the_collector_follows_a_pdf_on_another_domain_and_remembers_the_linking_page() -> None:
    collector, site, stored, _sleeps, _ = make_collector(pages())  # type: ignore[arg-type]

    collector.collect(SITE, NAME)

    by_url = {record.url: record for record in stored}
    elsewhere = by_url[f"https://{OTHER}/files/acme-profile.pdf"]
    assert elsewhere.content_type == "application/pdf"
    assert elsewhere.linked_from_url == SITE  # linked from the home page
    assert by_url[f"https://{HOST}/files/local.pdf"].linked_from_url == f"https://{HOST}/about"
    assert by_url[SITE].linked_from_url is None  # a page is not a linked PDF
    # only PDFs are followed off the website: a page on another domain is still not collected
    assert f"https://{OTHER}/other-page" not in by_url
    assert not any(request.url.endswith("/other-page") for request in site.seen)


def test_the_storage_function_records_the_page_that_linked_to_a_pdf(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, enqueue=False)
    database = Database(None, engine)
    page = store_source(
        database, run_id, organisation_id, SourceRecord(SITE, utc_now(), "text/html", "Home page")
    )
    pdf_url = f"https://{OTHER}/files/acme-profile.pdf"

    store_source(
        database,
        run_id,
        organisation_id,
        SourceRecord(pdf_url, utc_now(), "application/pdf", "Profile", "A. Writer", SITE),
    )
    store_source(  # a PDF found by the retrieval provider: linked from no page
        database,
        run_id,
        organisation_id,
        SourceRecord(f"https://{OTHER}/x.pdf", utc_now(), "application/pdf", "Other"),
    )
    store_source(  # linked from a page that was never stored: nothing to point at
        database,
        run_id,
        organisation_id,
        SourceRecord(
            f"https://{OTHER}/y.pdf", utc_now(), "application/pdf", "Third", None, "https://x.test/"
        ),
    )

    with Session(engine) as db:
        rows = {s.url: s for s in db.scalars(select(Source).where(Source.run_id == run_id))}
    assert rows[pdf_url].linked_from_source_id == page
    assert rows[f"https://{OTHER}/x.pdf"].linked_from_source_id is None
    assert rows[f"https://{OTHER}/y.pdf"].linked_from_source_id is None
    assert rows[SITE].linked_from_source_id is None


def test_storing_a_pdf_again_replaces_its_link(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, enqueue=False)
    database = Database(None, engine)
    page = store_source(
        database, run_id, organisation_id, SourceRecord(SITE, utc_now(), "text/html", "Home")
    )
    pdf = SourceRecord(f"https://{OTHER}/a.pdf", utc_now(), "application/pdf", "A", None, SITE)

    first = store_source(database, run_id, organisation_id, pdf)
    again = store_source(database, run_id, organisation_id, pdf)

    assert first == again
    with Session(engine) as db:
        assert db.get(Source, again).linked_from_source_id == page  # type: ignore[union-attr]


def test_the_recorded_link_makes_the_pdf_the_suppliers_claim() -> None:
    pdf = f"https://{OTHER}/files/acme-profile.pdf"
    assert classify_source(pdf, SITE) == "third_party"
    assert classify_source(pdf, SITE, linked_from_url=SITE) == "supplier_claim"


def classify_collected(stored: list[SourceRecord]) -> dict[str, str]:
    return {r.url: classify_source(r.url, SITE, linked_from_url=r.linked_from_url) for r in stored}


def test_a_page_redirected_to_another_site_is_stored_and_classified_on_the_final_address() -> None:
    final = f"https://{OTHER}/landing"
    pages = {
        (HOST, "/"): html("<a href='/about'>About</a>"),
        (HOST, "/about"): redirect(final),
        (OTHER, "/landing"): html("<p>The registry's own text.</p>"),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    kinds = classify_collected(stored)
    assert f"https://{HOST}/about" not in kinds
    assert kinds[final] == "third_party"


def test_a_redirect_inside_the_suppliers_domain_stays_its_own_claim() -> None:
    final = f"https://{SUBDOMAIN}/about-us"
    pages = {
        (HOST, "/"): html("<a href='/about'>About</a>"),
        (HOST, "/about"): redirect(final),
        (SUBDOMAIN, "/about-us"): html("<p>About Acme.</p>"),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    assert classify_collected(stored)[final] == "supplier_claim"


def test_a_redirected_pdf_is_classified_on_its_final_address() -> None:
    final = f"https://{OTHER}/real.pdf"
    pages = {
        (HOST, "/"): html("<a href='/files/report.pdf'>Report</a>"),
        (HOST, "/files/report.pdf"): redirect(final),
        (OTHER, "/real.pdf"): pdf_response(pdf_bytes("Registry document")),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    pdf = next(r for r in stored if r.content_type == "application/pdf")
    assert pdf.url == final and pdf.linked_from_url is None  # the link is not the claim
    assert classify_collected(stored)[final] == "third_party"


def test_a_linked_pdf_redirected_inside_its_host_stays_the_suppliers_claim() -> None:
    linked = f"https://{OTHER}/files/a.pdf"
    final = f"https://{OTHER}/files/b.pdf"
    pages = {
        (HOST, "/"): html(f"<a href='{linked}'>Profile</a>"),
        (OTHER, "/files/a.pdf"): redirect(final),
        (OTHER, "/files/b.pdf"): pdf_response(pdf_bytes("Profile of Acme")),
    }
    collector, _site, stored, _sleeps, _ = make_collector(pages)

    collector.collect(SITE, NAME)

    pdf = next(r for r in stored if r.content_type == "application/pdf")
    assert pdf.url == final and pdf.linked_from_url == SITE
    assert classify_collected(stored)[final] == "supplier_claim"

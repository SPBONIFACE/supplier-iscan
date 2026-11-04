"""A PDF linked from a page of the supplier's website (#23, owner decision of 27 Oct 2026): the
collector follows it even on another domain and remembers the page, and the storage function
records that page as `Source.linked_from_source_id`."""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.collection.source_store import SourceRecord, store_source
from app.db import Database, utc_now
from app.extraction.source_type import classify_source
from app.models import Source
from tests.collection.support import HOST, OTHER, html, make_collector, pdf_bytes, pdf_response
from tests.factories import create_organisation
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

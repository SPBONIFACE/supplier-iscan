"""Source type rules (#23): the supplier's own claim versus a third-party source. No database."""

import pytest

from app.extraction.source_type import classify_source, host_of, registry_domains

SITE = "https://www.acme.example"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # apex versus www: the same site, whichever way the website was confirmed
        ("https://acme.example/about", "supplier_claim"),
        ("https://www.acme.example/about", "supplier_claim"),
        ("http://WWW.ACME.EXAMPLE./about", "supplier_claim"),
        # a subdomain of the confirmed site, with or without www
        ("https://careers.acme.example/jobs", "supplier_claim"),
        ("https://www.shop.acme.example/", "supplier_claim"),
        # a country-domain variant that is not in the registry identifiers
        ("https://acme.fr/a-propos", "third_party"),
        ("https://www.acme.example.fr/", "third_party"),
        # look-alikes and unrelated sites
        ("https://notacme.example/", "third_party"),
        ("https://acme.example.evil.test/", "third_party"),
        ("https://news.example/acme", "third_party"),
    ],
)
def test_domain_rules(url: str, expected: str) -> None:
    assert classify_source(url, SITE) == expected


def test_the_website_may_be_confirmed_with_or_without_www_or_a_scheme() -> None:
    for website in ("https://acme.example", "acme.example", "https://www.acme.example/home"):
        assert classify_source("https://www.acme.example/x", website) == "supplier_claim"
        assert classify_source("https://acme.example/x", website) == "supplier_claim"


def test_a_site_confirmed_on_a_subdomain_does_not_cover_its_parent() -> None:
    assert classify_source("https://acme.example/", "https://eu.acme.example") == "third_party"
    assert (
        classify_source("https://eu.acme.example/x", "https://eu.acme.example") == "supplier_claim"
    )


def test_a_domain_in_the_registry_identifiers_is_the_suppliers_own() -> None:
    registry = registry_domains({"lei": "529900ACME00000000AA", "website": "https://acme.fr/"})

    assert registry == {"acme.fr"}
    assert classify_source("https://www.acme.fr/a-propos", SITE, registry) == "supplier_claim"
    assert classify_source("https://acme.de/", SITE, registry) == "third_party"


def test_registry_identifiers_that_are_not_domains_list_none() -> None:
    ids = {"lei": "529900ACME00000000AA", "wikidata_id": "Q123", "note": "see the register"}

    assert registry_domains(ids) == set()
    assert registry_domains(None) == set()
    assert registry_domains({"domains": ["acme.de", "https://www.acme.fr"]}) == {
        "acme.de",
        "acme.fr",
    }


def test_a_pdf_linked_from_a_page_of_the_website_is_the_suppliers_own_wherever_hosted() -> None:
    pdf = "https://cdn.files-host.example/reports/acme-2025.pdf"

    assert classify_source(pdf, SITE) == "third_party"
    assert classify_source(pdf, SITE, linked_from_url="https://www.acme.example/downloads") == (
        "supplier_claim"
    )
    assert classify_source(pdf, SITE, linked_from_url="https://acme.example/downloads") == (
        "supplier_claim"
    )


def test_a_pdf_linked_from_a_third_party_page_is_not() -> None:
    pdf = "https://cdn.files-host.example/reports/acme-2025.pdf"

    assert classify_source(pdf, SITE, linked_from_url="https://news.example/story") == (
        "third_party"
    )


def test_without_a_website_only_the_registry_domains_count() -> None:
    assert classify_source("https://acme.example/", None) == "third_party"
    assert classify_source("https://acme.fr/", None, {"acme.fr"}) == "supplier_claim"
    assert classify_source("https://x.example/a.pdf", None, linked_from_url="https://a.test") == (
        "third_party"
    )


def test_host_of() -> None:
    assert host_of("https://WWW.Example.com:8080/a?b") == "example.com"
    assert host_of("") is None
    assert host_of("https://[bad") is None  # an address that cannot be parsed never raises

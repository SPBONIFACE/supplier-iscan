"""#18: text extraction, sitemaps, page recognition, identity matching, rate limiter."""

import gzip
import logging
import unicodedata

import pytest

from app.collection.html_text import parse_html
from app.collection.identity import core_name, name_appears
from app.collection.limiter import DomainRateLimiter
from app.collection.pages import classify
from app.collection.pdf import extract_pdf
from app.collection.sitemap import parse_sitemap
from tests.collection.support import encrypted_pdf, pdf_bytes


def test_boilerplate_is_dropped_and_links_are_collected() -> None:
    page = parse_html(
        b"<nav>Menu</nav><header>Head</header><main><h1>Acme</h1><p>We make <b>bolts</b>.</p>"
        b"<script>var x=1</script><a href='/about'>About us</a></main>"
        b"<div role='navigation'>Skip</div><footer>Legal</footer><aside>Ad</aside>"
    )
    assert page.text == "Acme\nWe make bolts.\nAbout us"
    assert page.links == [("/about", "About us")]


@pytest.mark.parametrize(
    ("text", "charset", "meta"),
    [
        ("Société anonyme à Genève, l'été", "iso-8859-1", '<meta charset="iso-8859-1">'),
        (
            "Größe, Qualität und Straße",
            "cp1252",
            '<meta http-equiv="x" content="text/html; charset=windows-1252">',
        ),
        ("株式会社テスト 品質管理", "shift_jis", '<meta charset="shift_jis">'),
        ("北京供应商 质量认证", "utf-8", ""),
    ],
)
def test_declared_encodings_give_clean_nfc_text(text: str, charset: str, meta: str) -> None:
    document = f"<html><head>{meta}</head><body><p>{text}</p></body></html>".encode(charset)
    assert parse_html(document).text == text


def test_text_is_nfc_even_when_the_page_is_decomposed() -> None:
    decomposed = unicodedata.normalize("NFD", "Société Générale")
    text = parse_html(f"<p>{decomposed}</p>".encode()).text
    assert text == "Société Générale" and unicodedata.is_normalized("NFC", text)


def test_the_http_header_charset_wins_and_undeclared_latin1_is_not_garbled() -> None:
    body = "<p>Qualité</p>".encode("iso-8859-1")
    assert parse_html(body, "text/html; charset=iso-8859-1").text == "Qualité"
    assert parse_html(body).text == "Qualité"  # not UTF-8: falls back to Windows-1252


def test_a_page_without_text_is_empty() -> None:
    assert parse_html(b"<html><body><script>x</script><nav>m</nav></body></html>").text == ""


def test_sitemap_index_urlset_and_gzip() -> None:
    index = b"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><sitemap><loc>https://a.example/s1.xml</loc></sitemap></sitemapindex>"
    assert parse_sitemap(index, 10_000, 10).children == ["https://a.example/s1.xml"]
    urls = b"<urlset><url><loc> https://a.example/x </loc></url></urlset>"
    assert parse_sitemap(gzip.compress(urls), 10_000, 10).urls == ["https://a.example/x"]


def test_hostile_sitemaps_are_empty_results(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert parse_sitemap(b"<urlset><url><loc>x", 10_000, 10).urls == []  # malformed
    big = gzip.compress(b"<urlset>" + b"<url><loc>https://a.example/p</loc></url>" * 100_000)
    assert len(big) < 100_000
    assert parse_sitemap(big, 100_000, 10).urls == []  # decompresses past the cap
    assert parse_sitemap(b"\x1f\x8bnot gzip", 10_000, 10).urls == []
    bomb = b'<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    bomb += b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
    bomb += b"<urlset><url><loc>&c;&c;&c;</loc></url></urlset>"
    parse_sitemap(bomb, 10_000, 10)  # must return, not hang or crash
    many = b"<urlset>" + b"<url><loc>https://a.example/p</loc></url>" * 50 + b"</urlset>"
    assert len(parse_sitemap(many, 100_000, 10).urls) == 10


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://a.example/", "home"),
        ("https://a.example/en/about-us", "about"),
        ("https://a.example/qui-sommes-nous", "about"),
        ("https://a.example/%C3%BCber-uns", "about"),
        ("https://a.example/unternehmen/", "about"),
        ("https://a.example/sustainability", "sustainability"),
        ("https://a.example/developpement-durable", "sustainability"),
        ("https://a.example/nachhaltigkeit", "sustainability"),
        ("https://a.example/esg", "sustainability"),
        ("https://a.example/certifications", "certifications"),
        ("https://a.example/qualite", "certifications"),
        ("https://a.example/zertifizierungen", "certifications"),
        ("https://a.example/standorte", "locations"),
        ("https://a.example/nos-sites", "locations"),
        ("https://a.example/locations", "locations"),
        ("https://a.example/blog/post-1", None),
        ("https://a.example/isolation-thermique", None),  # "iso" is a whole word only
    ],
)
def test_page_names_in_english_french_and_german_are_recognised(url: str, kind: str | None) -> None:
    assert classify(url) == kind


def test_a_link_text_can_name_the_page() -> None:
    assert classify("https://a.example/p/42", "Nachhaltigkeit") == "sustainability"


def test_pdf_text_author_and_failures() -> None:
    pdf = extract_pdf(pdf_bytes("Hello report", "A. Writer"), 10)
    assert "Hello report" in pdf.text and pdf.author == "A. Writer"
    assert extract_pdf(encrypted_pdf(), 10).text == ""
    assert extract_pdf(b"%PDF-1.4 garbage", 10).text == ""
    assert extract_pdf(b"", 10).text == ""


def test_legal_form_case_and_accent_are_ignored() -> None:
    assert core_name("Société Générale Établissements S.A.S.") == "societe generale etablissements"
    assert core_name("SA") == "sa"
    assert name_appears("Müller Bolzen GmbH", ["Willkommen bei MULLER BOLZEN AG, seit 1950"])
    assert name_appears("Acme Supplies SA", ["Acme Supplies, Inc."])
    assert not name_appears("Acme Supplies SA", ["Other Corp makes supplies for Acme"])
    assert not name_appears("Acme SA", ["Acmeville is a town"])  # whole words only


def test_rate_limiter_enforces_the_minimum_delay_per_domain() -> None:
    clock = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    limiter = DomainRateLimiter(2.0, clock=lambda: clock[0], sleep=sleep)
    with limiter.slot("a.example"):
        pass
    clock[0] += 0.5
    with limiter.slot("a.example"):
        pass
    with limiter.slot("b.example"):  # another domain is not delayed
        pass
    assert sleeps == [1.5]

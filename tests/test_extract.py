"""Витяг тексту й контактів: деобфускація email, mailto, контактні посилання, усічення, хеш."""

from __future__ import annotations

from serp_scout.extract import (
    deobfuscate,
    extract_page,
    find_contact_links,
    find_emails,
    html_to_text,
    text_hash,
    truncate,
)


def test_deobfuscate_variants() -> None:
    assert deobfuscate("ads [at] site [dot] com") == "ads@site.com"
    assert deobfuscate("ads (at) site (dot) com") == "ads@site.com"
    assert deobfuscate("write to ads at site dot com today") == "write to ads@site.com today"
    assert deobfuscate("we met at the casino") == "we met at the casino"


def test_find_emails_dedup_and_junk() -> None:
    html = (
        '<a href="mailto:Partners@Example-Media.ca?subject=hi">mail</a> contact: ads [at] casino [dot] ca '
        "logo@2x.png image sentry@abc.io noreply@x.com ads@casino.ca"
    )
    assert find_emails(html) == ["partners@example-media.ca", "ads@casino.ca"]


def test_find_contact_links_relative_and_anchor() -> None:
    html = (
        '<a href="/advertise/">Advertise with us</a> <a href="/pricing">Pricing</a> '
        '<a href="https://x.ca/team">Our team</a> <a href="/media-kit.pdf">Download</a> '
        '<a href="/foo">Write for us</a> <a href="mailto:a@b.ca">Contact</a>'
    )
    links = find_contact_links(html, "https://www.casino.ca/best/")
    hrefs = [link["href"] for link in links]
    assert hrefs == [
        "https://www.casino.ca/advertise/",
        "https://www.casino.ca/media-kit.pdf",
        "https://www.casino.ca/foo",
    ]
    assert links[0]["anchor"] == "Advertise with us"


def test_truncate_head_tail() -> None:
    text = "A" * 100 + "B" * 100
    assert truncate(text, 150, 100) == text
    cut = truncate(text, 50, 20)
    assert cut.startswith("A" * 50) and cut.endswith("B" * 20) and "[...]" in cut


def test_text_hash_stable() -> None:
    assert text_hash("abc") == text_hash("abc") and text_hash("abc") != text_hash("abd")
    assert len(text_hash("x")) == 64


def test_html_to_text_fallback_for_tiny_pages() -> None:
    assert "Hello world" in html_to_text(
        "<html><body><p>Hello world</p><script>var x=1;</script></body></html>"
    )
    assert html_to_text("") == ""


def test_extract_page_html_and_text_modes() -> None:
    html = (
        "<html><body><article>"
        + "<p>Casino review paragraph.</p>" * 30
        + '<footer>ads [at] casino [dot] ca <a href="/contact/">Contact</a></footer></article></body></html>'
    )
    page = extract_page(html, is_html=True, base_url="https://casino.ca/", head=9000, tail=3000)
    assert page.emails == ["ads@casino.ca"]
    assert page.contact_links[0]["href"] == "https://casino.ca/contact/"
    assert page.text_len > 500 and page.text_hash == text_hash(page.text)

    snippet = extract_page(
        "Title\n\nSnippet with mail@site.ca", is_html=False, base_url="https://s.ca", head=10, tail=5
    )
    assert snippet.emails == ["mail@site.ca"] and snippet.contact_links == []
    assert "[...]" in snippet.text

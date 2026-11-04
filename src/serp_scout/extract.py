"""Витяг тексту й контактів зі сторінки: trafilatura, email з деобфускацією, контактні посилання, усічення.

Контент сторінки — дані, не інструкції: тут лише детерміновані регулярні вирази, без інтерпретації.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import trafilatura

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r"mailto:([^\"'?\s>]+)", re.IGNORECASE)
_AT_OBFUSCATED_RE = re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.IGNORECASE)
_DOT_OBFUSCATED_RE = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.IGNORECASE)
# «name at domain dot tld» лише коли є і «at», і «dot» — інакше забагато хибних збігів
_WORDS_OBFUSCATED_RE = re.compile(
    r"\b([A-Za-z0-9._%+\-]+)\s+at\s+([A-Za-z0-9\-]+)\s+dot\s+([A-Za-z]{2,})\b", re.IGNORECASE
)
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_CONTACT_HINT_RE = re.compile(
    r"contact|advertis|write[\s\-]*for[\s\-]*us|about|media[\s\-]*kit|partnership|sponsor", re.IGNORECASE
)
_JUNK_EMAIL_RE = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|css|js)$|example\.|sentry|wixpress|@\d+\.\d+|noreply|no-reply|@localhost",
    re.IGNORECASE,
)
MAX_EMAILS = 5
MAX_CONTACT_LINKS = 10


@dataclass
class ExtractedPage:
    """Текст сторінки (вже усічений), його хеш і детерміновані контактні підказки."""

    text: str
    text_hash: str
    text_len: int
    emails: list[str] = field(default_factory=list)
    contact_links: list[dict[str, str]] = field(default_factory=list)


def html_to_text(html: str) -> str:
    """Основний текст сторінки через trafilatura; якщо вона нічого не знайшла — грубе зняття тегів."""
    if not html or not html.strip():
        return ""
    try:
        text = trafilatura.extract(html, include_links=False, include_comments=False) or ""
    except Exception:  # noqa: BLE001 - будь-який збій парсера не має валити сторінку
        text = ""
    if len(text.strip()) < 200:
        fallback = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", html))
        fallback = html_lib.unescape(re.sub(r"\s+", " ", fallback)).strip()
        if len(fallback) > len(text):
            text = fallback
    return text.strip()


def deobfuscate(text: str) -> str:
    """`ads [at] site [dot] com`, `ads (at) site (dot) com`, `ads at site dot com` → `ads@site.com`."""
    result = _AT_OBFUSCATED_RE.sub("@", text)
    result = _DOT_OBFUSCATED_RE.sub(".", result)
    return _WORDS_OBFUSCATED_RE.sub(r"\1@\2.\3", result)


def find_emails(*sources: str) -> list[str]:
    """Email з тексту та HTML (включно з `mailto:`), у нижньому регістрі, без дублів і сміття."""
    found: list[str] = []
    for source in sources:
        if not source:
            continue
        candidates = _MAILTO_RE.findall(source) + _EMAIL_RE.findall(deobfuscate(html_lib.unescape(source)))
        for raw in candidates:
            email = raw.strip().strip(".,;:").lower()
            if _EMAIL_RE.fullmatch(email) and not _JUNK_EMAIL_RE.search(email) and email not in found:
                found.append(email)
    return found[:MAX_EMAILS]


def find_contact_links(html: str, base_url: str) -> list[dict[str, str]]:
    """Посилання з contact/advertis/write-for-us/about/media-kit/partnership/sponsor у href або анкорі."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, inner in _ANCHOR_RE.findall(html or ""):
        anchor = html_lib.unescape(_TAG_RE.sub(" ", inner))
        anchor = re.sub(r"\s+", " ", anchor).strip()
        if href.lower().startswith(("mailto:", "javascript:", "tel:")):
            continue
        if not (_CONTACT_HINT_RE.search(href) or _CONTACT_HINT_RE.search(anchor)):
            continue
        absolute = urljoin(base_url, html_lib.unescape(href.strip()))
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append({"href": absolute, "anchor": anchor[:120]})
        if len(links) >= MAX_CONTACT_LINKS:
            break
    return links


def truncate(text: str, head: int, tail: int) -> str:
    """Голова + хвіст: довгі сторінки часто мають контакти у футері."""
    if len(text) <= head + tail:
        return text
    return text[:head].rstrip() + "\n[...]\n" + text[-tail:].lstrip()


def text_hash(text: str) -> str:
    """sha256 тексту — ключ кешу розмітки."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_page(
    html_or_text: str,
    *,
    is_html: bool,
    base_url: str,
    head: int,
    tail: int,
    prefetched_text: str | None = None,
) -> ExtractedPage:
    """Повний витяг: текст (усічений), хеш, email, контактні посилання."""
    if is_html:
        full_text = prefetched_text if prefetched_text is not None else html_to_text(html_or_text)
        emails = find_emails(html_or_text, full_text)
        links = find_contact_links(html_or_text, base_url)
    else:
        full_text = html_or_text.strip()
        emails = find_emails(full_text)
        links = []
    text = truncate(full_text, head, tail)
    return ExtractedPage(
        text=text, text_hash=text_hash(text), text_len=len(full_text), emails=emails, contact_links=links
    )

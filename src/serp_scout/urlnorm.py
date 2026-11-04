"""Нормалізація URL і визначення домену (офлайн `tldextract`, без мережі)."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# Офлайн: лише вшитий знімок списку публічних суфіксів, жодних запитів у мережу.
_extract = tldextract.TLDExtract(suffix_list_urls=())

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"gclid", "fbclid", "msclkid", "yclid", "mc_cid", "mc_eid", "ref_src"}


def normalize_url(url: str) -> str:
    """Прибирає фрагмент, utm_*/клік-ідентифікатори, зводить схему й хост до нижнього регістру."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.endswith(":80") and scheme == "http":
        host = host[:-3]
    if host.endswith(":443") and scheme == "https":
        host = host[:-4]
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, urlencode(query, doseq=True), ""))


def domain_of(url: str) -> str:
    """Хост без `www.`; піддомени зберігаються (`en.wikipedia.org`, `apps.apple.com`)."""
    ext = _extract(url)
    labels = [ext.subdomain, ext.domain, ext.suffix]
    fqdn = ".".join(part for part in labels if part).lower()
    if not fqdn:
        fqdn = urlsplit(url).netloc.lower()
    if fqdn.startswith("www."):
        fqdn = fqdn[4:]
    return fqdn


def registered_domain(url: str) -> str:
    """Домен другого рівня з суфіксом (`casino.ca`, `wikipedia.org`) — для групування."""
    ext = _extract(url)
    return ".".join(part for part in (ext.domain, ext.suffix) if part).lower()


def url_key(url: str) -> str:
    """Стабільний короткий ключ URL (sha256, 16 символів) — для касет і HTML-фікстур."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]

"""Завантаження сторінок: httpx (мобільний UA) → Jina Reader → SERP-сніпет; 4 потоки, 1 с на домен.

Фолбек на reader — при 403/503/429, капчі або порожньому тексті (< `min_text_chars`); якщо й reader
не дав тексту — `method=snippet` з title + snippet із видачі.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from serp_scout.config import FetchSettings, mask_secrets
from serp_scout.extract import html_to_text
from serp_scout.urlnorm import domain_of

_BLOCK_STATUSES = {403, 429, 503}
_CAPTCHA_MARKERS = ("captcha", "cf-challenge", "just a moment...", "attention required", "access denied")


@dataclass
class FetchResult:
    """Результат завантаження одного URL."""

    method: str  # httpx | reader | snippet
    http_status: int | None
    html_or_text: str
    error: str | None = None
    text: str | None = None  # текст, уже витягнутий під час перевірки (щоб не парсити двічі)

    @property
    def is_html(self) -> bool:
        """True лише для `httpx`: тоді `html_or_text` — сирий HTML, інакше вже текст."""
        return self.method == "httpx"


class PageFetcher:
    """Потокобезпечний завантажувач з ретраями, лімітом байтів і паузою між запитами на один домен."""

    def __init__(
        self,
        settings: FetchSettings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._client = client or httpx.Client(
            timeout=settings.timeout_s,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-CA,en;q=0.9"},
        )
        self._domain_lock = threading.Lock()
        self._domain_last: dict[str, float] = {}

    # --- внутрішнє -------------------------------------------------------------------------

    def _throttle(self, url: str) -> None:
        """Не частіше ніж раз на `per_domain_delay_s` до одного домену."""
        if self.settings.per_domain_delay_s <= 0:
            return
        domain = domain_of(url)
        with self._domain_lock:
            now = time.monotonic()
            wait = self._domain_last.get(domain, 0.0) + self.settings.per_domain_delay_s - now
            self._domain_last[domain] = max(now, self._domain_last.get(domain, 0.0)) + (
                self.settings.per_domain_delay_s if wait > 0 else 0.0
            )
        if wait > 0:
            self._sleep(wait)

    def _get_limited(self, url: str) -> tuple[int, str]:
        """GET зі стрімом; читання обривається після `max_bytes` (решта відкидається)."""
        chunks: list[bytes] = []
        total = 0
        with self._client.stream("GET", url) as response:
            status = response.status_code
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= self.settings.max_bytes:
                    break
            encoding = response.encoding or "utf-8"
        body = b"".join(chunks)[: self.settings.max_bytes]
        return status, body.decode(encoding, errors="replace")

    def _get_with_retries(self, url: str) -> tuple[int, str]:
        """До `retries` повторів на таймаут/мережевий збій з бекофом 1, 2 с."""
        last_exc: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                self._throttle(url)
                return self._get_limited(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < self.settings.retries:
                    self._sleep(float(2**attempt))
        raise last_exc or RuntimeError("невідомий збій завантаження")

    def _looks_blocked(self, status: int, html: str) -> bool:
        head = html[:4000].lower()
        return status in _BLOCK_STATUSES or any(marker in head for marker in _CAPTCHA_MARKERS)

    def _reader(self, url: str) -> tuple[int, str]:
        """Фолбек Jina Reader: `https://r.jina.ai/<url>` повертає текст/markdown сторінки."""
        self._throttle(self.settings.reader_fallback)
        response = self._client.get(
            self.settings.reader_fallback.rstrip("/") + "/" + url,
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
        )
        return response.status_code, response.text[: self.settings.max_bytes]

    # --- публічне --------------------------------------------------------------------------

    def fetch(self, url: str, title: str = "", snippet: str = "") -> FetchResult:
        """Повертає найкращий доступний результат; ніколи не кидає виняток."""
        errors: list[str] = []
        status: int | None = None
        try:
            status, html = self._get_with_retries(url)
            if status < 400 and not self._looks_blocked(status, html):
                text = html_to_text(html)
                if len(text) >= self.settings.min_text_chars:
                    return FetchResult("httpx", status, html, None, text)
                errors.append(f"httpx {status}: текст {len(text)} символів")
            else:
                errors.append(f"httpx {status}: заблоковано або помилка")
        except Exception as exc:  # noqa: BLE001 - будь-який збій одного URL не валить прогін
            errors.append(f"httpx: {type(exc).__name__}")

        try:
            reader_status, text = self._reader(url)
            if reader_status == 200 and len(text.strip()) >= self.settings.min_text_chars:
                return FetchResult(
                    "reader", reader_status, text.strip(), mask_secrets("; ".join(errors)), text.strip()
                )
            errors.append(f"reader {reader_status}: текст {len(text.strip())} символів")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reader: {type(exc).__name__}")

        fallback = "\n\n".join(part for part in (title.strip(), snippet.strip()) if part)
        return FetchResult("snippet", status, fallback, mask_secrets("; ".join(errors)), fallback)

    def fetch_many(self, items: list[tuple[str, str, str]]) -> dict[str, FetchResult]:
        """Паралельно (`concurrency` потоків) завантажує `(url, title, snippet)`; ключ — url."""
        results: dict[str, FetchResult] = {}
        with ThreadPoolExecutor(max_workers=max(1, self.settings.concurrency)) as pool:
            futures = {pool.submit(self.fetch, url, title, snippet): url for url, title, snippet in items}
            for future, url in futures.items():
                results[url] = future.result()
        return results

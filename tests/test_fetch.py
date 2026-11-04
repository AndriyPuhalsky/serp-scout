"""Завантаження сторінок (respx): httpx → reader → snippet, ретраї, ліміт байтів, пауза на домен."""

from __future__ import annotations

import httpx
import pytest
import respx

from serp_scout.config import FetchSettings
from serp_scout.fetch import PageFetcher

URL = "https://www.example-casino.ca/best/"
READER = "https://r.jina.ai/" + URL
LONG_HTML = (
    "<html><body><article><h1>Best casinos</h1>"
    + "<p>Review text about casinos in Canada.</p>" * 40
    + "</article></body></html>"
)


def _fetcher(**overrides) -> tuple[PageFetcher, list[float]]:
    sleeps: list[float] = []
    settings = FetchSettings(per_domain_delay_s=0, retries=2, max_bytes=20_000, **overrides)
    return PageFetcher(settings, sleep=sleeps.append), sleeps


@respx.mock
def test_httpx_ok() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text=LONG_HTML))
    fetcher, _ = _fetcher()
    result = fetcher.fetch(URL, "t", "s")
    assert result.method == "httpx" and result.http_status == 200
    assert result.is_html and "Best casinos" in (result.text or "")


@respx.mock
def test_403_falls_back_to_reader() -> None:
    respx.get(URL).mock(return_value=httpx.Response(403, text="forbidden"))
    respx.get(READER).mock(return_value=httpx.Response(200, text="Title: x\n\n" + "Reader text. " * 60))
    fetcher, _ = _fetcher()
    result = fetcher.fetch(URL, "t", "s")
    assert result.method == "reader" and result.http_status == 200
    assert not result.is_html and "Reader text" in result.html_or_text


@respx.mock
def test_reader_empty_falls_back_to_snippet() -> None:
    respx.get(URL).mock(return_value=httpx.Response(503, text="unavailable"))
    respx.get(READER).mock(return_value=httpx.Response(200, text="too short"))
    fetcher, _ = _fetcher()
    result = fetcher.fetch(URL, "Title here", "Snippet here")
    assert result.method == "snippet"
    assert result.html_or_text == "Title here\n\nSnippet here"
    assert result.error and "httpx 503" in result.error and "reader 200" in result.error


@respx.mock
def test_captcha_page_goes_to_reader() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text="<title>Just a moment...</title>" + LONG_HTML))
    respx.get(READER).mock(return_value=httpx.Response(200, text="Real content. " * 60))
    fetcher, _ = _fetcher()
    assert fetcher.fetch(URL).method == "reader"


@respx.mock
def test_timeout_then_retry_succeeds() -> None:
    route = respx.get(URL).mock(side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, text=LONG_HTML)])
    fetcher, sleeps = _fetcher()
    result = fetcher.fetch(URL)
    assert result.method == "httpx" and route.call_count == 2
    assert sleeps == [1.0]  # бекоф між спробами


@respx.mock
def test_body_over_limit_is_cut() -> None:
    big = "<html><body>" + "<p>" + "x" * 50_000 + "</p></body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, text=big))
    fetcher, _ = _fetcher()
    result = fetcher.fetch(URL)
    assert len(result.html_or_text) <= 20_000


@respx.mock
def test_per_domain_delay_sleeps_between_requests() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text=LONG_HTML))
    respx.get(URL + "2/").mock(return_value=httpx.Response(200, text=LONG_HTML))
    sleeps: list[float] = []
    fetcher = PageFetcher(FetchSettings(per_domain_delay_s=1.0, retries=0), sleep=sleeps.append)
    fetcher.fetch(URL)
    fetcher.fetch(URL + "2/")
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0


@respx.mock
def test_fetch_many_returns_all() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, text=LONG_HTML))
    respx.get("https://other.ca/").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://r.jina.ai/https://other.ca/").mock(side_effect=httpx.ConnectError("down"))
    fetcher, _ = _fetcher()
    results = fetcher.fetch_many([(URL, "a", "b"), ("https://other.ca/", "Other", "Snip")])
    assert results[URL].method == "httpx"
    assert results["https://other.ca/"].method == "snippet"


def test_fetch_settings_defaults_match_spec() -> None:
    s = FetchSettings()
    assert s.timeout_s == 15 and s.retries == 2 and s.max_bytes == 2_000_000 and s.concurrency == 4
    assert pytest.approx(s.per_domain_delay_s) == 1.0

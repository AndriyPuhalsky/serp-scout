"""Провайдери SERP: фікстури, розбір SerpApi, ретраї й маскування ключа (respx)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from serp_scout.config import Keyword, SerpSettings
from serp_scout.providers import SerpError, hits_from_serpapi
from serp_scout.providers.fixture import FixtureProvider
from serp_scout.providers.serpapi import SERPAPI_URL, SerpApiProvider

FIXTURES = Path(__file__).parent / "fixtures" / "serp"
KW = Keyword(id=1, keyword="online casino canada", cluster="Грошові")
FAKE_KEY = "serpapi-test-key-0123456789"


def _payload(n: int = 10) -> dict:
    return {
        "search_metadata": {"status": "Success"},
        "search_parameters": {"q": KW.keyword, "api_key": FAKE_KEY},
        "organic_results": [
            {"position": i, "link": f"https://example{i}.ca/page", "title": f"T{i}", "snippet": f"S{i}"}
            for i in range(1, n + 1)
        ],
    }


def _provider(tmp_path: Path) -> SerpApiProvider:
    return SerpApiProvider(SerpSettings(), tmp_path / "raw", "2026-11-04", api_key=FAKE_KEY, backoff_max_s=0)


def test_fixture_provider_returns_top10() -> None:
    hits = FixtureProvider(FIXTURES).search(KW)
    assert len(hits) == 10
    assert [h.position for h in hits] == list(range(1, 11))
    assert hits[0].url.startswith("https://")
    assert hits[0].title and hits[0].snippet


def test_fixture_provider_missing_file() -> None:
    with pytest.raises(SerpError):
        FixtureProvider(FIXTURES).search(Keyword(id=99, keyword="nope"))


def test_hits_from_serpapi_filters_and_limits() -> None:
    payload = _payload(12)
    payload["organic_results"].insert(0, {"position": 0, "link": "javascript:void(0)", "title": "bad"})
    hits = hits_from_serpapi(payload, 10)
    assert len(hits) == 10 and hits[0].position == 1
    assert hits_from_serpapi({"error": "Google hasn't returned any results for this query."}) == []


@respx.mock
def test_serpapi_success_saves_raw_without_key(tmp_path: Path) -> None:
    route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(200, json=_payload()))
    hits = _provider(tmp_path).search(KW)
    assert len(hits) == 10
    params = route.calls.last.request.url.params
    assert params["engine"] == "google" and params["gl"] == "ca" and params["device"] == "mobile"
    assert params["location"] == "Canada" and params["num"] == "10" and params["google_domain"] == "google.ca"
    raw = (tmp_path / "raw" / "2026-11-04" / "1.json").read_text()
    assert "organic_results" in raw and FAKE_KEY not in raw


@respx.mock
def test_serpapi_retries_on_429_then_succeeds(tmp_path: Path) -> None:
    route = respx.get(SERPAPI_URL).mock(
        side_effect=[httpx.Response(429, text="slow down"), httpx.Response(200, json=_payload())]
    )
    hits = _provider(tmp_path).search(KW)
    assert len(hits) == 10 and route.call_count == 2


@respx.mock
def test_serpapi_500_three_times_raises_masked(tmp_path: Path) -> None:
    route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(SerpError) as exc_info:
        _provider(tmp_path).search(KW)
    assert route.call_count == 3
    assert FAKE_KEY not in str(exc_info.value)


@respx.mock
def test_serpapi_401_no_retry_key_masked(tmp_path: Path) -> None:
    route = respx.get(SERPAPI_URL).mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(SerpError) as exc_info:
        _provider(tmp_path).search(KW)
    assert route.call_count == 1
    assert "api_key=***" in str(exc_info.value) and FAKE_KEY not in str(exc_info.value)


@respx.mock
def test_serpapi_timeout_then_ok(tmp_path: Path) -> None:
    respx.get(SERPAPI_URL).mock(side_effect=[httpx.ReadTimeout("t"), httpx.Response(200, json=_payload())])
    assert len(_provider(tmp_path).search(KW)) == 10


def test_serpapi_requires_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    with pytest.raises(SerpError):
        SerpApiProvider(SerpSettings(), tmp_path, "2026-11-04")

"""Живий провайдер SerpApi: Google, Канада, mobile, топ-10; сира відповідь — у `raw/<дата>/<id>.json`."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    wait_none,
)

from serp_scout.config import ENV_SERPAPI_KEY, Keyword, SerpSettings, get_secret, mask_secrets
from serp_scout.providers.base import SerpError, SerpHit, hits_from_serpapi

SERPAPI_URL = "https://serpapi.com/search.json"


class _RetryableSerpError(Exception):
    """429 / 5xx / таймаут — варто повторити."""


class SerpApiProvider:
    """GET https://serpapi.com/search.json з ретраями (3 спроби, бекоф 2–8 с з джитером)."""

    name = "serpapi"

    def __init__(
        self,
        settings: SerpSettings,
        raw_dir: Path,
        run_date: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        attempts: int = 3,
        backoff_initial_s: float = 2.0,
        backoff_max_s: float = 8.0,
        timeout_s: float = 30.0,
    ) -> None:
        self.settings = settings
        self.raw_dir = raw_dir
        self.run_date = run_date
        self._api_key = api_key or get_secret(ENV_SERPAPI_KEY)
        if not self._api_key:
            raise SerpError(f"{ENV_SERPAPI_KEY} не задано — додайте в .env або запустіть з --offline")
        self._client = client or httpx.Client(timeout=timeout_s)
        self._attempts = attempts
        self._backoff = (backoff_initial_s, backoff_max_s)

    def _params(self, keyword: Keyword) -> dict[str, str]:
        s = self.settings
        return {
            "engine": s.engine,
            "q": keyword.keyword,
            "location": s.location,
            "gl": s.gl,
            "hl": s.hl,
            "device": s.device,
            "num": str(s.num),
            "google_domain": s.google_domain,
            "api_key": self._api_key or "",
        }

    def _get_once(self, keyword: Keyword) -> dict:
        """Один HTTP-запит; 429/5xx/таймаут → _RetryableSerpError, інші 4xx → SerpError."""
        try:
            response = self._client.get(SERPAPI_URL, params=self._params(keyword))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _RetryableSerpError(f"мережа: {type(exc).__name__}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableSerpError(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            # URL містить api_key — у повідомлення потрапляє лише маскована версія
            raise SerpError(
                mask_secrets(f"SerpApi HTTP {response.status_code} для «{keyword.keyword}»: {response.url}")
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SerpError(f"SerpApi повернув не JSON для «{keyword.keyword}»") from exc

    def _retrying(self) -> Retrying:
        initial, maximum = self._backoff
        wait = (
            wait_none() if maximum <= 0 else wait_exponential_jitter(initial=initial, max=maximum, jitter=1.0)
        )
        return Retrying(
            stop=stop_after_attempt(self._attempts),
            wait=wait,
            retry=retry_if_exception_type(_RetryableSerpError),
            reraise=True,
        )

    def search(self, keyword: Keyword) -> list[SerpHit]:
        """Повертає до `num` органічних результатів; зберігає сиру відповідь."""
        try:
            payload = self._retrying()(self._get_once, keyword)
        except _RetryableSerpError as exc:
            raise SerpError(
                mask_secrets(f"SerpApi не відповів за {self._attempts} спроби для «{keyword.keyword}»: {exc}")
            ) from exc
        self._save_raw(keyword, payload)
        return hits_from_serpapi(payload, self.settings.num)

    def _save_raw(self, keyword: Keyword, payload: dict) -> None:
        """Записує сиру відповідь у `<raw_dir>/<run_date>/<keyword_id>.json` (без ключа в параметрах)."""
        target = self.raw_dir / self.run_date / f"{keyword.id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        safe = dict(payload)
        params = safe.get("search_parameters")
        if isinstance(params, dict):
            safe["search_parameters"] = {k: v for k, v in params.items() if k != "api_key"}
        target.write_text(json.dumps(safe, ensure_ascii=False, indent=1), encoding="utf-8")

"""Спільні типи провайдерів SERP і розбір відповіді у форматі SerpApi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from serp_scout.config import Keyword


class SerpError(RuntimeError):
    """Збій провайдера SERP по одному ключу (повідомлення вже без секретів)."""


@dataclass(frozen=True, slots=True)
class SerpHit:
    """Один органічний результат топ-10."""

    position: int
    url: str
    title: str
    snippet: str


class SerpProvider(Protocol):
    """Будь-який провайдер видачі: повертає до `num` органічних результатів для ключа."""

    name: str

    def search(self, keyword: Keyword) -> list[SerpHit]:  # pragma: no cover - протокол
        """Топ-`num` органічних результатів для ключа; збій одного ключа → `SerpError`."""


def hits_from_serpapi(payload: dict[str, Any], num: int = 10) -> list[SerpHit]:
    """Бере лише `organic_results`, перші `num` за `position`; реклама й блоки ігноруються.

    Відповідь 200 з полем `error` («Google hasn't returned any results…») — порожня видача.
    """
    if not isinstance(payload, dict):
        raise SerpError("відповідь SerpApi не є JSON-об'єктом")
    results = payload.get("organic_results") or []
    hits: list[SerpHit] = []
    for index, item in enumerate(results, start=1):
        link = (item.get("link") or "").strip()
        if not link.startswith(("http://", "https://")):
            continue
        hits.append(
            SerpHit(
                position=int(item.get("position") or index),
                url=link,
                title=str(item.get("title") or "").strip(),
                snippet=str(item.get("snippet") or "").strip(),
            )
        )
    hits.sort(key=lambda h: h.position)
    return hits[:num]

"""Офлайн-провайдер: читає `tests/fixtures/serp/<keyword_id>.json` у форматі SerpApi."""

from __future__ import annotations

import json
from pathlib import Path

from serp_scout.config import Keyword
from serp_scout.providers.base import SerpError, SerpHit, hits_from_serpapi


class FixtureProvider:
    """Повертає збережену видачу без мережі й ключів (для `--offline`, тестів і демо)."""

    name = "fixture"

    def __init__(self, fixtures_dir: Path, num: int = 10) -> None:
        self.fixtures_dir = fixtures_dir
        self.num = num

    def search(self, keyword: Keyword) -> list[SerpHit]:
        """Читає `<fixtures_dir>/<keyword.id>.json`; немає файлу або не JSON → `SerpError`."""
        path = self.fixtures_dir / f"{keyword.id}.json"
        if not path.exists():
            raise SerpError(f"немає фікстури {path.name} для «{keyword.keyword}»")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SerpError(f"фікстура {path.name} не є валідним JSON") from exc
        return hits_from_serpapi(payload, self.num)

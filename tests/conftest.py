"""Спільні фікстури тестів: ізольована тека даних/сайту, налаштування, БД."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from serp_scout import store
from serp_scout.config import Settings, load_settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Налаштування проєкту з даними й сайтом у тимчасовій теці (нічого не пише в репозиторій)."""
    monkeypatch.setenv("SERP_SCOUT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SERP_SCOUT_SITE_DIR", str(tmp_path / "site"))
    monkeypatch.setenv("SERP_SCOUT_FIXTURES_DIR", str(FIXTURES))
    return load_settings()


@pytest.fixture
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Порожня БД зі схемою і ключами."""
    connection = store.connect(settings.paths.db)
    store.init_db(connection)
    store.upsert_keywords(connection, settings.keywords)
    yield connection
    connection.close()

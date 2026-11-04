"""config: завантаження yml, перекриття з оточення, маскування секретів."""

from __future__ import annotations

from pathlib import Path

import pytest

from serp_scout.config import load_settings, mask_secrets

# Фейкові значення збираються в рантаймі, щоб у файлі не було рядків, схожих на справжні ключі
FAKE_SERP = "abcdef" + "1234567890"
FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "verysecretvalue"
FAKE_TG = "123456789" + ":" + "A" * 35


def test_settings_load_keywords_and_brands(settings) -> None:
    assert len(settings.keywords) == 10
    assert settings.keywords[0].keyword == "online casino canada"
    assert "JackpotCity" in settings.brands
    assert settings.serp.device == "mobile" and settings.serp.gl == "ca"
    assert settings.llm.model == "claude-sonnet-5-5"


def test_data_dir_override(settings, tmp_path: Path) -> None:
    assert settings.paths.db == tmp_path / "data" / "serp.sqlite"
    assert settings.paths.export_dir == tmp_path / "data" / "export"
    assert settings.paths.report == tmp_path / "site" / "data" / "report.json"


def test_budget_env_overrides_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SERP_SCOUT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_BUDGET_USD", "0.25")
    assert load_settings().llm.budget_usd == 0.25


def test_mask_secrets_env_and_patterns() -> None:
    env = {"SERPAPI_KEY": FAKE_SERP, "ANTHROPIC_API_KEY": FAKE_ANTHROPIC, "HOME": "/x"}
    text = f"GET ?api_key={FAKE_SERP} and {FAKE_ANTHROPIC} token {FAKE_TG}"
    masked = mask_secrets(text, env)
    assert FAKE_SERP not in masked
    assert "verysecretvalue" not in masked
    assert "api_key=***" in masked
    assert FAKE_TG not in masked


def test_demo_mode_uses_separate_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERP_SCOUT_DATA_DIR", raising=False)
    monkeypatch.delenv("SERP_SCOUT_SITE_DIR", raising=False)
    demo = load_settings(demo=True)
    root = demo.paths.root
    assert demo.paths.data_dir == root / "data" / "demo"
    assert demo.paths.db == root / "data" / "demo" / "serp.sqlite"
    assert demo.paths.raw_dir == root / "data" / "demo" / "raw"
    assert demo.paths.export_dir == root / "data" / "demo" / "export"
    assert demo.paths.costs == root / "data" / "demo" / "costs.jsonl"
    assert demo.paths.report == root / "site" / "data" / "report.demo.json"
    live = load_settings()
    assert (
        live.paths.db == root / "data" / "serp.sqlite"
        and live.paths.report == root / "site" / "data" / "report.json"
    )


def test_demo_mode_env_overrides_win(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SERP_SCOUT_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("SERP_SCOUT_SITE_DIR", str(tmp_path / "s"))
    demo = load_settings(demo=True)
    assert demo.paths.db == tmp_path / "d" / "serp.sqlite"
    assert demo.paths.report == tmp_path / "s" / "data" / "report.json"

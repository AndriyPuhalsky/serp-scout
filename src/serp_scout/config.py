"""Налаштування serp-scout: `config/*.yml` + `.env`, шляхи даних, маскування секретів.

Секрети ніколи не потрапляють у `Settings` — їх читають через `get_secret()` безпосередньо
з оточення в момент використання, а `mask_secrets()` прибирає їх з будь-яких повідомлень.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Корінь проєкту: src/serp_scout/config.py → parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Назви змінних оточення (лише назви — значення читаються в рантаймі)
ENV_SERPAPI_KEY = "SERPAPI_KEY"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_BUDGET = "LLM_BUDGET_USD"
ENV_DATA_DIR = "SERP_SCOUT_DATA_DIR"
ENV_SITE_DIR = "SERP_SCOUT_SITE_DIR"
ENV_FIXTURES_DIR = "SERP_SCOUT_FIXTURES_DIR"

_SECRET_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$")
_SECRET_PATTERNS = (
    re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"),  # токен Telegram-бота
)


class Keyword(BaseModel):
    """Ключове слово з `config/keywords.yml`."""

    id: int
    keyword: str
    cluster: str = ""


class SerpSettings(BaseModel):
    """Параметри SerpApi (Google, Канада, mobile)."""

    provider: str = "serpapi"
    engine: str = "google"
    location: str = "Canada"
    gl: str = "ca"
    hl: str = "en"
    device: str = "mobile"
    num: int = 10
    google_domain: str = "google.ca"


class FetchSettings(BaseModel):
    """Параметри завантаження сторінок."""

    user_agent: str = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) Mobile Safari"
    timeout_s: float = 15.0
    retries: int = 2
    max_bytes: int = 2_000_000
    concurrency: int = 4
    per_domain_delay_s: float = 1.0
    reader_fallback: str = "https://r.jina.ai/"
    text_head_chars: int = 9000
    text_tail_chars: int = 3000
    min_text_chars: int = 500


class LlmSettings(BaseModel):
    """Параметри розмітки LLM; `budget_usd` вже з урахуванням `LLM_BUDGET_USD`."""

    model: str = "claude-sonnet-5-5"
    prompt_version: str = "v1"
    max_tokens: int = 1200
    price_input_per_mtok_usd: float = 2.0
    price_output_per_mtok_usd: float = 10.0
    budget_usd_default: float = 3.0
    budget_usd: float = 3.0


class LinksSettings(BaseModel):
    """Параметри проходу партнерських редиректів (бонус І6)."""

    max_hops: int = 10
    affiliate_patterns: list[str] = Field(default_factory=list)


class Paths(BaseModel):
    """Усі шляхи вже абсолютні; `SERP_SCOUT_DATA_DIR` / `SERP_SCOUT_SITE_DIR` перекривають теки."""

    root: Path
    config_dir: Path
    data_dir: Path
    db: Path
    raw_dir: Path
    export_dir: Path
    costs: Path
    site_dir: Path
    report: Path
    fixtures_dir: Path


class Settings(BaseModel):
    """Зведені налаштування пайплайну."""

    serp: SerpSettings
    fetch: FetchSettings
    llm: LlmSettings
    links: LinksSettings
    paths: Paths
    keywords: list[Keyword]
    brands: dict[str, list[str]]


def _read_yaml(path: Path) -> dict:
    """Читає yml у словник; порожній файл → {}."""
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _rebase(raw_path: str, root: Path, prefix: str, override: Path | None) -> Path:
    """Розв'язує шлях із settings.yml відносно кореня, а за наявності override — замість `prefix/`."""
    if override is not None and raw_path.startswith(prefix + "/"):
        return override / raw_path[len(prefix) + 1 :]
    return root / raw_path


def load_settings(
    root: Path | None = None, env: Mapping[str, str] | None = None, demo: bool = False
) -> Settings:
    """Завантажує `config/*.yml`, підтягує `.env` і будує `Settings`.

    `demo=True` (режим `--offline`): дані йдуть у `data/demo/`, звіт — у `site/data/report.demo.json`,
    щоб `make demo` не перезаписував реальний дамп; явні `SERP_SCOUT_DATA_DIR` / `SERP_SCOUT_SITE_DIR`
    перекривають ці шляхи.
    """
    root = (root or PROJECT_ROOT).resolve()
    load_dotenv(root / ".env", override=False)
    env = env if env is not None else os.environ

    config_dir = root / "config"
    raw = _read_yaml(config_dir / "settings.yml")
    keywords_raw = _read_yaml(config_dir / "keywords.yml").get("keywords", [])
    brands_raw = _read_yaml(config_dir / "brands.yml").get("brands", {})

    llm = LlmSettings(**raw.get("llm", {}))
    budget_env = env.get(ENV_BUDGET)
    llm.budget_usd = float(budget_env) if budget_env else llm.budget_usd_default

    data_override = Path(env[ENV_DATA_DIR]).resolve() if env.get(ENV_DATA_DIR) else None
    site_override = Path(env[ENV_SITE_DIR]).resolve() if env.get(ENV_SITE_DIR) else None
    if demo and data_override is None:
        data_override = root / "data" / "demo"
    p = raw.get("paths", {})
    report_rel = p.get("report", "site/data/report.json")
    if demo and site_override is None:
        report_rel = str(Path(report_rel).with_name("report.demo.json"))
    fixtures_dir = Path(env[ENV_FIXTURES_DIR]) if env.get(ENV_FIXTURES_DIR) else root / "tests" / "fixtures"
    paths = Paths(
        root=root,
        config_dir=config_dir,
        data_dir=data_override or root / "data",
        db=_rebase(p.get("db", "data/serp.sqlite"), root, "data", data_override),
        raw_dir=_rebase(p.get("raw_dir", "data/raw"), root, "data", data_override),
        export_dir=_rebase(p.get("export_dir", "data/export"), root, "data", data_override),
        costs=_rebase(p.get("costs", "data/costs.jsonl"), root, "data", data_override),
        site_dir=site_override or root / "site",
        report=_rebase(report_rel, root, "site", site_override),
        fixtures_dir=fixtures_dir.resolve(),
    )
    return Settings(
        serp=SerpSettings(**raw.get("serp", {})),
        fetch=FetchSettings(**raw.get("fetch", {})),
        llm=llm,
        links=LinksSettings(**raw.get("links", {})),
        paths=paths,
        keywords=[Keyword(**k) for k in keywords_raw],
        brands={str(k): [str(v) for v in vs] for k, vs in brands_raw.items()},
    )


def get_secret(name: str) -> str | None:
    """Повертає значення секрету з оточення (або None). Ніколи не логувати результат."""
    value = os.environ.get(name, "").strip()
    return value or None


def mask_secrets(text: str, env: Mapping[str, str] | None = None) -> str:
    """Замінює в тексті значення секретів з оточення та типові шаблони ключів на `***`."""
    env = env if env is not None else os.environ
    masked = text
    for name, value in env.items():
        if _SECRET_NAME_RE.search(name) and len(value) >= 8 and value in masked:
            masked = masked.replace(value, "***")
    for pattern in _SECRET_PATTERNS:
        masked = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "***", masked)
    return masked

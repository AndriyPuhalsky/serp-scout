"""Підсумок прогону (`RunSummary`), дата UTC, git-sha і запис помилок без секретів."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serp_scout.config import mask_secrets


@dataclass
class RunSummary:
    """Підсумок прогону для CLI/Telegram."""

    run_id: int
    run_date: str
    mode: str
    status: str = "running"
    serp_calls: int = 0
    urls_total: int = 0
    urls_new: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    labels_new: int = 0
    labels_cached: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    errors: list[dict[str, Any]] = field(default_factory=list)
    exports: list[Path] = field(default_factory=list)
    report: Path | None = None

    def counters(self) -> dict[str, Any]:
        """Лічильники для запису в `runs` (ключі збігаються з колонками таблиці)."""
        return {
            "serp_calls": self.serp_calls,
            "urls_total": self.urls_total,
            "urls_new": self.urls_new,
            "pages_fetched": self.pages_fetched,
            "pages_failed": self.pages_failed,
            "labels_new": self.labels_new,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def today_utc() -> str:
    """Дата прогону — UTC (сторож у GitHub Actions порівнює з `date -u +%F`)."""
    return datetime.now(UTC).date().isoformat()


def git_sha(root: Path) -> str | None:
    """Короткий sha поточного коміту для `runs.git_sha`; None, якщо git недоступний або комітів немає."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def record_error(summary: RunSummary, stage: str, subject: str, exc: Exception) -> None:
    """Додає помилку етапу (serp | page | llm | export | pipeline) до підсумку, маскуючи секрети."""
    summary.errors.append(
        {"stage": stage, "subject": subject, "error": mask_secrets(f"{type(exc).__name__}: {exc}")[:300]}
    )

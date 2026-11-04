"""Облік вартості LLM: рядок на виклик у `data/costs.jsonl` і підсумки для `stats`."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_cost(
    path: Path, run_date: str, url_id: int, model: str, input_tokens: int, output_tokens: int, cost_usd: float
) -> None:
    """Дописує запис `{ts, run_date, url_id, model, input_tokens, output_tokens, cost_usd}`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "run_date": run_date,
        "url_id": url_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize(path: Path) -> dict[str, Any]:
    """Підсумок за датами: виклики, токени, вартість; `total` — сума по всіх."""
    by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # пошкоджений рядок не валить статистику
            day = by_date[str(rec.get("run_date", "?"))]
            day["calls"] += 1
            day["input_tokens"] += int(rec.get("input_tokens") or 0)
            day["output_tokens"] += int(rec.get("output_tokens") or 0)
            day["cost_usd"] += float(rec.get("cost_usd") or 0)
    total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for day in by_date.values():
        for key in total:
            total[key] += day[key]
    return {"by_date": dict(sorted(by_date.items())), "total": total}

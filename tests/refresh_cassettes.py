"""Знімає касети LLM (`tests/fixtures/llm/<url_key>.json`) з живої бази — без жодних викликів API.

Запуск: `uv run python -m tests.refresh_cassettes [--db data/serp.sqlite] [--version v2]`.
Для кожного URL береться найсвіжіша мітка заданої версії промпту (крім міток-збоїв). Бренди —
`brands_json` з бази (уже об'єднані з лексиконом), тож офлайн-прогін дає ті самі бренди, що й сайт.
Касета шукається лише за `url_key` (Р-015), хеш тексту сторінки на неї не впливає.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from serp_scout.label_schema import PageLabel
from serp_scout.labeler import FAILED_LABEL_REASON
from serp_scout.urlnorm import url_key

ROOT = Path(__file__).resolve().parent.parent
NOTE = "Реальна розмітка живого прогону; в офлайн-режимі вартість не нараховується"

QUERY = """
SELECT u.url, l.* FROM labels l JOIN urls u ON u.id = l.url_id
WHERE l.prompt_version = ? AND l.reason != ?
ORDER BY l.url_id, l.labeled_at DESC, l.id DESC
"""


def cassette_from_row(row: sqlite3.Row) -> dict:
    """Рядок `labels` → касета у форматі, який читає `Labeler._cassette`."""
    label = PageLabel.model_validate(
        {
            "site_type": row["site_type"],
            "relevant_for_placement": bool(row["relevant"]),
            "confidence": row["confidence"],
            "reason": row["reason"],
            "brands_mentioned": [
                {"name": b, "normalized": b, "context": ""} for b in json.loads(row["brands_json"] or "[]")
            ],
            "contact": json.loads(row["contact_json"] or "{}"),
            "placement_signals": json.loads(row["placement_signals_json"] or "[]"),
        }
    )
    return {
        "url": row["url"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "labeled_at": row["labeled_at"],
        "note": NOTE,
        "usage": {
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "cost_usd": round(row["cost_usd"] or 0.0, 5),
        },
        "label": label.model_dump(mode="json"),
    }


def refresh(db: Path, version: str, out_dir: Path) -> int:
    """Перезаписує касети для всіх URL з міткою `version`; повертає кількість записаних."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    seen: set[int] = set()
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in conn.execute(QUERY, (version, FAILED_LABEL_REASON)):
        if row["url_id"] in seen:
            continue
        seen.add(row["url_id"])
        path = out_dir / f"{url_key(row['url'])}.json"
        text = json.dumps(cassette_from_row(row), ensure_ascii=False, indent=1)
        path.write_text(text, encoding="utf-8")
    conn.close()
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description="Касети LLM з живої бази (без викликів API)")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "serp.sqlite")
    parser.add_argument("--version", default="v2")
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "llm")
    args = parser.parse_args()
    n = refresh(args.db, args.version, args.out)
    print(f"Касет записано: {n} (prompt_version={args.version}) → {args.out}")


if __name__ == "__main__":
    main()

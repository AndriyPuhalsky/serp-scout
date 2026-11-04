"""Збирає `site/data/report.json` для сайту-звіту: KPI, рядки розміщення, бренди, історія, прогони."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serp_scout.config import Keyword
from serp_scout.store import latest_run_date


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except ValueError:
        return default


_CONTACT_KEYS = ("email", "contact_page", "telegram", "form", "other")


def _contact(raw: str | None) -> dict[str, Any] | None:
    """`null`, якщо контакту немає; інакше повний об'єкт з усіма п'ятьма ключами."""
    data = _loads(raw, None)
    if not isinstance(data, dict) or not any(data.get(k) for k in _CONTACT_KEYS):
        return None
    contact = {k: data.get(k) for k in _CONTACT_KEYS}
    contact["form"] = bool(contact["form"])
    return contact


def _error_text(err: Any) -> str:
    """Помилка прогону одним рядком для сайту."""
    if isinstance(err, dict):
        return f"{err.get('stage', '?')} · {err.get('subject', '')}: {err.get('error', '')}".strip()
    return str(err)


def _positions_by_url(conn: sqlite3.Connection) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """url_id → {keyword_id: [{date, position}, …]} за всю історію."""
    result: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute("SELECT url_id, keyword_id, run_date, position FROM v_history").fetchall():
        result[r["url_id"]][str(r["keyword_id"])].append({"date": r["run_date"], "position": r["position"]})
    return result


def _rows(conn: sqlite3.Connection, run_date: str) -> list[dict[str, Any]]:
    """Унікальні URL останнього снапшота з останньою розміткою й історією позицій."""
    positions = _positions_by_url(conn)
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for r in conn.execute("SELECT * FROM v_latest WHERE run_date = ?", (run_date,)).fetchall():
        if r["url_id"] in seen:
            continue
        seen.add(r["url_id"])
        rows.append(
            {
                "url": r["url"],
                "domain": r["domain"],
                "title": r["title"] or "",
                "site_type": r["site_type"],
                "relevant": bool(r["relevant"]) if r["relevant"] is not None else None,
                "confidence": round(float(r["confidence"]), 2) if r["confidence"] is not None else None,
                "reason": r["reason"] or "",
                "brands": _loads(r["brands_json"], []),
                "contact": _contact(r["contact_json"]),
                "placement_signals": _loads(r["placement_signals_json"], []),
                "positions": positions.get(r["url_id"], {}),
                "best_position": r["best_position"],
                "needs_review": bool(r["needs_review"]) if r["needs_review"] is not None else True,
                # Без рядка `pages` маємо лише дані видачі — функціонально це `snippet`
                "method": r["method"] if r["method"] in ("httpx", "reader", "snippet") else "snippet",
                "model": r["model"],
                "page_error": r["page_error"],
            }
        )
    rows.sort(key=lambda x: (not x["relevant"], -(x["confidence"] or 0), x["best_position"] or 99))
    return rows


def _runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM runs ORDER BY id").fetchall():
        out.append(
            {
                "date": r["run_date"],
                "status": r["status"],
                "cost_usd": round(float(r["cost_usd"] or 0), 4),
                "serp_calls": r["serp_calls"],
                "urls_total": r["urls_total"],
                "urls_new": r["urls_new"],
                "pages_fetched": r["pages_fetched"],
                "pages_failed": r["pages_failed"],
                "labels_new": r["labels_new"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "errors": _loads(r["errors_json"], []),
                "mode": r["mode"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
            }
        )
    return out


def build_report(conn: sqlite3.Connection, keywords: list[Keyword]) -> dict[str, Any]:
    """Повна структура `report.json` (див. docs/02 і завдання на site_build)."""
    run_date = latest_run_date(conn)
    runs = _runs(conn)
    rows = _rows(conn, run_date) if run_date else []
    run_dates = [r["d"] for r in conn.execute("SELECT DISTINCT run_date AS d FROM serp_results ORDER BY d")]
    latest = next((r for r in reversed(runs) if r["date"] == run_date), runs[-1] if runs else None)
    relevant = sum(1 for r in rows if r["relevant"])
    # Бренди рахуємо без урахування регістру («BluffBet» = «Bluffbet»), показуємо перше написання
    brand_counter: Counter[str] = Counter()
    brand_display: dict[str, str] = {}
    for r in rows:
        for brand in set(r["brands"]):
            key = brand.casefold()
            brand_display.setdefault(key, brand)
            brand_counter[key] += 1
    contacts = sum(
        1 for r in rows if r["contact"] and (r["contact"]["email"] or r["contact"]["contact_page"])
    )
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "run_dates": run_dates,
        "latest_run": latest
        and {
            "date": latest["date"],
            "status": latest["status"],
            "cost_usd": latest["cost_usd"],
            "serp_calls": latest["serp_calls"],
            "urls_total": latest["urls_total"],
            "urls_new": latest["urls_new"],
            "labels_new": latest["labels_new"],
            "errors": [_error_text(e) for e in latest["errors"]],
            "errors_count": len(latest["errors"]),
        },
        "kpi": {
            "keywords": len(keywords),
            "urls": len(rows),
            "relevant": relevant,
            "relevant_pct": round(relevant * 100 / len(rows), 1) if rows else 0.0,
            "brands": len(brand_counter),
            "contacts": contacts,
            "needs_review": sum(1 for r in rows if r["needs_review"]),
            "cost_total_usd": round(sum(r["cost_usd"] for r in runs), 4),
        },
        "keywords": [{"id": k.id, "keyword": k.keyword, "cluster": k.cluster} for k in keywords],
        "rows": rows,
        "brands_top": [{"brand": brand_display[k], "pages": n} for k, n in brand_counter.most_common(30)],
        "runs": [
            {
                k: r[k]
                for k in (
                    "date",
                    "status",
                    "cost_usd",
                    "urls_total",
                    "urls_new",
                    "labels_new",
                    "serp_calls",
                    "pages_failed",
                )
            }
            for r in runs
        ],
    }


def write_report(conn: sqlite3.Connection, keywords: list[Keyword], report_path: Path) -> Path:
    """Записує report.json (створює теку)."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(build_report(conn, keywords), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report_path

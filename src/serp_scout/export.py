"""Експорт CSV у `<data_dir>/export/`: снапшот дня, остання розмітка на URL, історія позицій."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from serp_scout.store import latest_run_date

SERP_COLUMNS = ["keyword", "position", "url", "domain", "run_date"]
LABEL_COLUMNS = [
    "url", "domain", "site_type", "relevant", "confidence", "brands", "contact_email", "contact_page",
    "reason", "needs_review", "placement_signals", "model", "method",
]  # fmt: skip
HISTORY_COLUMNS = ["keyword", "url", "run_date", "position"]


def _write_csv(path: Path, columns: list[str], rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")  # LF, щоб git не скаржився на CRLF
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def export_serp(conn: sqlite3.Connection, export_dir: Path, run_date: str) -> Path:
    """`serp_<run_date>.csv`: keyword, position, url, domain, run_date."""
    rows = conn.execute(
        "SELECT keyword, position, url, domain, run_date FROM v_history WHERE run_date = ? "
        "ORDER BY keyword_id, position",
        (run_date,),
    ).fetchall()
    return _write_csv(export_dir / f"serp_{run_date}.csv", SERP_COLUMNS, [list(r) for r in rows])


def export_labels(conn: sqlite3.Connection, export_dir: Path) -> Path:
    """`labels.csv`: остання розмітка кожного URL."""
    rows = conn.execute(
        """
        SELECT u.url, u.domain, l.site_type, l.relevant, l.confidence, l.brands_json, l.contact_json,
               l.reason,
               l.needs_review, l.placement_signals_json, l.model, p.method
        FROM labels l
        JOIN (SELECT url_id, MAX(id) AS id FROM labels GROUP BY url_id) m ON m.id = l.id
        JOIN urls u ON u.id = l.url_id
        LEFT JOIN pages p ON p.url_id = l.url_id
        ORDER BY l.relevant DESC, l.confidence DESC, u.domain
        """
    ).fetchall()
    out: list[list] = []
    for r in rows:
        brands = json.loads(r["brands_json"] or "[]")
        contact = json.loads(r["contact_json"] or "{}")
        out.append(
            [
                r["url"],
                r["domain"],
                r["site_type"],
                int(r["relevant"] or 0),
                round(float(r["confidence"] or 0), 2),
                "; ".join(brands),
                contact.get("email") or "",
                contact.get("contact_page") or "",
                r["reason"] or "",
                int(r["needs_review"] or 0),
                "; ".join(json.loads(r["placement_signals_json"] or "[]")),
                r["model"] or "",
                r["method"] or "",
            ]
        )
    return _write_csv(export_dir / "labels.csv", LABEL_COLUMNS, out)


def export_history(conn: sqlite3.Connection, export_dir: Path) -> Path:
    """`history.csv`: keyword, url, run_date, position — усі снапшоти."""
    rows = conn.execute("SELECT keyword, url, run_date, position FROM v_history").fetchall()
    return _write_csv(export_dir / "history.csv", HISTORY_COLUMNS, [list(r) for r in rows])


def run_summary_text(conn: sqlite3.Connection, run_date: str) -> str:
    """Короткий текст для Telegram (без HTML): дата, статус, лічильники, вартість, помилки."""
    run = conn.execute(
        "SELECT * FROM runs WHERE run_date = ? ORDER BY id DESC LIMIT 1", (run_date,)
    ).fetchone()
    kpi = conn.execute(
        """
        SELECT COUNT(*) AS urls, COALESCE(SUM(relevant), 0) AS relevant
        FROM (SELECT url_id, MAX(relevant) AS relevant FROM v_latest WHERE run_date = ? GROUP BY url_id)
        """,
        (run_date,),
    ).fetchone()
    brands: set[str] = set()
    for r in conn.execute("SELECT brands_json FROM v_latest WHERE run_date = ?", (run_date,)).fetchall():
        brands.update(b.casefold() for b in json.loads(r["brands_json"] or "[]"))  # як у report.json
    urls, relevant = int(kpi["urls"] or 0), int(kpi["relevant"] or 0)
    pct = round(relevant * 100 / urls, 1) if urls else 0.0
    if run is None:
        return f"serp-scout · {run_date}: прогону в runs немає, у снапшоті {urls} URL."
    errors = json.loads(run["errors_json"] or "[]")
    return "\n".join(
        [
            f"serp-scout · прогін {run_date} · статус: {run['status']}",
            f"SERP-виклики: {run['serp_calls']} · URL: {run['urls_total']} (нових {run['urls_new']})",
            f"Релевантних для розміщення: {relevant} з {urls} ({pct}%) · брендів: {len(brands)}",
            f"LLM-виклики: {run['labels_new']} · вартість прогону: ${float(run['cost_usd'] or 0):.2f}",
            f"Помилок: {len(errors)}",
        ]
    )


def export_summary(conn: sqlite3.Connection, export_dir: Path, run_date: str) -> Path:
    """`summary.txt` — його читає `daily.yml` і передає в Telegram."""
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / "summary.txt"
    path.write_text(run_summary_text(conn, run_date) + "\n", encoding="utf-8")
    return path


def export_all(conn: sqlite3.Connection, export_dir: Path, run_date: str | None = None) -> list[Path]:
    """CSV ×3 + summary.txt; дата за замовчуванням — останній снапшот."""
    run_date = run_date or latest_run_date(conn)
    if run_date is None:
        return []
    return [
        export_serp(conn, export_dir, run_date),
        export_labels(conn, export_dir),
        export_history(conn, export_dir),
        export_summary(conn, export_dir, run_date),
    ]

"""Сховище SQLite: з'єднання, схема, ідемпотентний снапшот дня, сторінки, розмітка, прогони.

Правила ідемпотентності (docs/02): той самий день → `INSERT OR REPLACE` за
`(run_date, keyword_id, position)`; `urls` — upsert за `url` (first_seen/last_seen/best_position);
`pages` і `labels` не дублюються за `url_id` і `(url_id, prompt_version, text_hash)`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serp_scout.config import Keyword
from serp_scout.providers.base import SerpHit
from serp_scout.schema import SCHEMA_SQL
from serp_scout.urlnorm import domain_of, is_google_host, normalize_url


def now_iso() -> str:
    """Поточний час UTC у ISO 8601 без мікросекунд."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    """Відкриває БД (створює теку), вмикає зовнішні ключі, повертає рядки як `sqlite3.Row`."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Створює таблиці, індекси й представлення, якщо їх ще немає."""
    conn.executescript(SCHEMA_SQL)
    # Міграція старих БД: колонка pages.final_url з'явилась пізніше за схему
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pages)")}
    if "final_url" not in cols:
        conn.execute("ALTER TABLE pages ADD COLUMN final_url TEXT")
    conn.commit()


def upsert_keywords(conn: sqlite3.Connection, keywords: Iterable[Keyword]) -> None:
    """Синхронізує `keywords` з `config/keywords.yml` (id — з конфігу)."""
    conn.executemany(
        "INSERT INTO keywords(id, keyword, cluster) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET keyword = excluded.keyword, cluster = excluded.cluster",
        [(k.id, k.keyword, k.cluster) for k in keywords],
    )
    conn.commit()


def upsert_url(conn: sqlite3.Connection, url: str, run_date: str, position: int) -> tuple[int, bool]:
    """Upsert `urls`; повертає `(url_id, is_new)`. URL нормалізується, домен без `www.`."""
    norm = normalize_url(url)
    row = conn.execute("SELECT id FROM urls WHERE url = ?", (norm,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO urls(url, domain, first_seen, last_seen, best_position) VALUES (?, ?, ?, ?, ?)",
            (norm, domain_of(norm), run_date, run_date, position),
        )
        return int(cur.lastrowid), True
    conn.execute(
        "UPDATE urls SET first_seen = MIN(first_seen, ?), last_seen = MAX(last_seen, ?), "
        "best_position = MIN(COALESCE(best_position, ?), ?) WHERE id = ?",
        (run_date, run_date, position, position, row["id"]),
    )
    return int(row["id"]), False


def upsert_snapshot(conn: sqlite3.Connection, run_date: str, keyword_id: int, hits: list[SerpHit]) -> int:
    """Записує снапшот дня для ключа без дублів; повертає кількість нових URL."""
    new_urls = 0
    with conn:
        for hit in hits:
            url_id, is_new = upsert_url(conn, hit.url, run_date, hit.position)
            new_urls += int(is_new)
            conn.execute(
                "INSERT OR REPLACE INTO serp_results(run_date, keyword_id, position, url_id, title, snippet) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_date, keyword_id, hit.position, url_id, hit.title, hit.snippet),
            )
        # Позиції, яких у новій видачі немає (видача стала коротшою), прибираємо
        if hits:
            conn.execute(
                "DELETE FROM serp_results WHERE run_date = ? AND keyword_id = ? AND position > ?",
                (run_date, keyword_id, max(h.position for h in hits)),
            )
    return new_urls


def snapshot_urls(conn: sqlite3.Connection, run_date: str) -> list[sqlite3.Row]:
    """Унікальні URL снапшота дня з ключами, за якими вони в топ-10, та найкращою позицією дня."""
    return conn.execute(
        """
        SELECT u.id AS url_id, u.url, u.domain,
               MIN(s.position) AS position,
               GROUP_CONCAT(k.keyword, ' | ') AS keywords,
               MAX(s.title) AS title, MAX(s.snippet) AS snippet
        FROM serp_results s
        JOIN urls u ON u.id = s.url_id
        JOIN keywords k ON k.id = s.keyword_id
        WHERE s.run_date = ?
        GROUP BY u.id
        ORDER BY MIN(s.position), u.id
        """,
        (run_date,),
    ).fetchall()


def get_page(conn: sqlite3.Connection, url_id: int) -> sqlite3.Row | None:
    """Рядок `pages` для URL або None."""
    return conn.execute("SELECT * FROM pages WHERE url_id = ?", (url_id,)).fetchone()


def upsert_page(conn: sqlite3.Connection, url_id: int, fields: dict[str, Any]) -> None:
    """Записує/оновлює рядок `pages` (один на URL)."""
    cols = [
        "fetched_at",
        "method",
        "http_status",
        "text_hash",
        "text_len",
        "text_path",
        "emails_json",
        "contact_links_json",
        "error",
        "final_url",
    ]
    values = [fields.get(c) for c in cols]
    assignments = ", ".join(f"{c} = excluded.{c}" for c in cols)
    with conn:
        conn.execute(
            f"INSERT INTO pages(url_id, {', '.join(cols)}) VALUES (?{', ?' * len(cols)}) "
            f"ON CONFLICT(url_id) DO UPDATE SET {assignments}",
            [url_id, *values],
        )


def apply_final_url(conn: sqlite3.Connection, url_id: int, final_url: str | None) -> bool:
    """Для URL-редиректу Google (`domain` = google.*) пише кінцеву адресу і домен кінцевого сайту.

    Ключ `urls.url` (а отже `url_key`, касети, історія позицій) не змінюється. Повертає True,
    якщо домен оновлено.
    """
    if not final_url:
        return False
    row = conn.execute("SELECT domain FROM urls WHERE id = ?", (url_id,)).fetchone()
    new_domain = domain_of(final_url)
    if row is None or not is_google_host(row["domain"]) or is_google_host(new_domain):
        return False
    with conn:
        conn.execute("UPDATE urls SET domain = ? WHERE id = ?", (new_domain, url_id))
        conn.execute("UPDATE pages SET final_url = ? WHERE url_id = ?", (final_url, url_id))
    return True


def google_redirect_urls(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """URL, чий домен досі google.* (нерозгорнутий `goto`): `id`, `url`."""
    rows = conn.execute("SELECT id, url, domain FROM urls ORDER BY id").fetchall()
    return [r for r in rows if is_google_host(r["domain"])]


def get_label(
    conn: sqlite3.Connection, url_id: int, prompt_version: str, text_hash: str
) -> sqlite3.Row | None:
    """Кеш розмітки: той самий URL, промпт і текст → повторний виклик LLM не потрібен."""
    return conn.execute(
        "SELECT * FROM labels WHERE url_id = ? AND prompt_version = ? AND text_hash = ?",
        (url_id, prompt_version, text_hash),
    ).fetchone()


def upsert_label(conn: sqlite3.Connection, url_id: int, fields: dict[str, Any]) -> None:
    """Записує розмітку; повторна за тим самим ключем (`--relabel`) перезаписує рядок."""
    cols = [
        "prompt_version",
        "text_hash",
        "site_type",
        "relevant",
        "confidence",
        "reason",
        "brands_json",
        "contact_json",
        "placement_signals_json",
        "needs_review",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "labeled_at",
    ]
    values = [fields.get(c) for c in cols]
    update_cols = [c for c in cols if c not in ("prompt_version", "text_hash")]
    assignments = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    with conn:
        conn.execute(
            f"INSERT INTO labels(url_id, {', '.join(cols)}) VALUES (?{', ?' * len(cols)}) "
            f"ON CONFLICT(url_id, prompt_version, text_hash) DO UPDATE SET {assignments}",
            [url_id, *values],
        )


def start_run(conn: sqlite3.Connection, run_date: str, mode: str, git_sha: str | None) -> int:
    """Створює рядок `runs` зі статусом `running`; повертає run_id."""
    with conn:
        cur = conn.execute(
            "INSERT INTO runs(run_date, started_at, status, mode, git_sha) VALUES (?, ?, 'running', ?, ?)",
            (run_date, now_iso(), mode, git_sha),
        )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection, run_id: int, status: str, counters: dict[str, Any], errors: list[dict[str, Any]]
) -> None:
    """Закриває прогін: статус, лічильники, вартість, помилки (JSON)."""
    allowed = {
        "serp_calls",
        "urls_total",
        "urls_new",
        "pages_fetched",
        "pages_failed",
        "labels_new",
        "input_tokens",
        "output_tokens",
        "cost_usd",
    }
    sets = {k: v for k, v in counters.items() if k in allowed}
    assignments = ", ".join(f"{k} = ?" for k in sets)
    with conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, errors_json = ?"
            f"{', ' + assignments if sets else ''} WHERE id = ?",
            [now_iso(), status, json.dumps(errors, ensure_ascii=False), *sets.values(), run_id],
        )


def latest_run_date(conn: sqlite3.Connection) -> str | None:
    """Дата останнього снапшота в `serp_results` (або None, якщо БД порожня)."""
    row = conn.execute("SELECT MAX(run_date) AS d FROM serp_results").fetchone()
    return row["d"] if row and row["d"] else None


def count(conn: sqlite3.Connection, table: str) -> int:
    """COUNT(*) таблиці (для тестів і підсумків)."""
    return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

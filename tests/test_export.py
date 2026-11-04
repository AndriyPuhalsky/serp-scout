"""Експорт CSV і summary.txt."""

from __future__ import annotations

import csv
import json

from serp_scout import store
from serp_scout.export import HISTORY_COLUMNS, LABEL_COLUMNS, SERP_COLUMNS, export_all, run_summary_text
from serp_scout.providers.base import SerpHit


def _seed(conn) -> None:
    hits = [SerpHit(i, f"https://www.site{i}.ca/", f"T{i}", f"S{i}") for i in range(1, 4)]
    store.upsert_snapshot(conn, "2026-11-04", 1, hits)
    url_id = conn.execute("SELECT id FROM urls WHERE url LIKE '%site1%'").fetchone()["id"]
    store.upsert_page(conn, url_id, {"method": "httpx", "text_hash": "h", "text_len": 1000})
    store.upsert_label(
        conn,
        url_id,
        {
            "prompt_version": "v1",
            "text_hash": "h",
            "site_type": "review_affiliate",
            "relevant": 1,
            "confidence": 0.9,
            "reason": "Рейтинг казино",
            "brands_json": json.dumps(["JackpotCity", "Betway"]),
            "contact_json": json.dumps({"email": "ads@site1.ca", "contact_page": None}),
            "cost_usd": 0.01,
        },
    )
    run_id = store.start_run(conn, "2026-11-04", "offline", None)
    store.finish_run(
        conn,
        run_id,
        "ok",
        {"serp_calls": 1, "urls_total": 3, "urls_new": 3, "labels_new": 1, "cost_usd": 0.01},
        [],
    )


def test_export_all_files_and_columns(conn, settings) -> None:
    _seed(conn)
    paths = export_all(conn, settings.paths.export_dir)
    names = sorted(p.name for p in paths)
    assert names == ["history.csv", "labels.csv", "serp_2026-11-04.csv", "summary.txt"]
    by_name = {p.name: p for p in paths}
    with by_name["serp_2026-11-04.csv"].open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == SERP_COLUMNS and len(rows) == 4
    assert rows[1] == ["online casino canada", "1", "https://www.site1.ca/", "site1.ca", "2026-11-04"]
    with by_name["labels.csv"].open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == LABEL_COLUMNS
    assert rows[0]["brands"] == "JackpotCity; Betway" and rows[0]["contact_email"] == "ads@site1.ca"
    with by_name["history.csv"].open(encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == HISTORY_COLUMNS


def test_summary_text_lines(conn) -> None:
    _seed(conn)
    text = run_summary_text(conn, "2026-11-04")
    lines = text.splitlines()
    assert 4 <= len(lines) <= 6 and "<" not in text
    assert "2026-11-04" in lines[0] and "статус: ok" in lines[0]
    assert "Релевантних для розміщення: 1 з 3 (33.3%)" in lines[2] and "брендів: 2" in lines[2]
    assert "$0.01" in lines[3] and lines[4] == "Помилок: 0"


def test_export_empty_db(conn, settings) -> None:
    assert export_all(conn, settings.paths.export_dir) == []

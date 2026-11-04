"""Сховище: ідемпотентність снапшота, історія, best_position, нормалізація URL і домену."""

from __future__ import annotations

from serp_scout import store
from serp_scout.providers.base import SerpHit
from serp_scout.urlnorm import domain_of, normalize_url, registered_domain, url_key


def _hits(n: int = 10, shift: int = 0) -> list[SerpHit]:
    return [
        SerpHit(i, f"https://www.site{(i + shift - 1) % n + 1}.ca/p?utm_source=x#frag", f"T{i}", f"S{i}")
        for i in range(1, n + 1)
    ]


def test_same_day_twice_no_duplicates(conn) -> None:
    store.upsert_snapshot(conn, "2026-11-04", 1, _hits())
    store.upsert_snapshot(conn, "2026-11-04", 1, _hits())
    assert store.count(conn, "serp_results") == 10
    assert store.count(conn, "urls") == 10


def test_other_day_adds_history_not_urls(conn) -> None:
    new_first = store.upsert_snapshot(conn, "2026-11-04", 1, _hits())
    new_second = store.upsert_snapshot(conn, "2026-11-05", 1, _hits(shift=1))
    assert new_first == 10 and new_second == 0
    assert store.count(conn, "serp_results") == 20
    assert store.count(conn, "urls") == 10
    history = conn.execute("SELECT COUNT(*) AS n FROM v_history").fetchone()["n"]
    assert history == 20


def test_best_position_and_seen_dates(conn) -> None:
    store.upsert_snapshot(conn, "2026-11-04", 1, [SerpHit(5, "https://www.casino.ca/", "t", "s")])
    store.upsert_snapshot(conn, "2026-11-05", 1, [SerpHit(2, "https://casino.ca/#top", "t", "s")])
    store.upsert_snapshot(conn, "2026-11-06", 1, [SerpHit(7, "https://casino.ca/", "t", "s")])
    rows = conn.execute("SELECT * FROM urls").fetchall()
    assert len(rows) == 2  # www.casino.ca і casino.ca — різні хости, той самий домен
    row = conn.execute("SELECT * FROM urls WHERE url = 'https://casino.ca/'").fetchone()
    assert row["best_position"] == 2
    assert row["first_seen"] == "2026-11-05" and row["last_seen"] == "2026-11-06"


def test_shorter_snapshot_removes_stale_positions(conn) -> None:
    store.upsert_snapshot(conn, "2026-11-04", 1, _hits(10))
    store.upsert_snapshot(conn, "2026-11-04", 1, _hits(10)[:7])
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM serp_results WHERE run_date='2026-11-04'").fetchone()["n"]
        == 7
    )


def test_normalize_url() -> None:
    assert (
        normalize_url("HTTPS://WWW.Casino.ca/Path?utm_source=g&b=2&gclid=1#frag")
        == "https://www.casino.ca/Path?b=2"
    )
    assert normalize_url("https://example.com") == "https://example.com/"
    assert url_key("https://example.com/#a") == url_key("https://example.com/")


def test_domain_of_strips_www_keeps_subdomains() -> None:
    assert domain_of("https://www.casino.ca/x") == "casino.ca"
    assert domain_of("https://en.wikipedia.org/wiki/Online_casino") == "en.wikipedia.org"
    assert domain_of("https://apps.apple.com/ca/app/x") == "apps.apple.com"
    assert registered_domain("https://en.wikipedia.org/wiki/X") == "wikipedia.org"


def test_v_latest_joins_latest_label(conn) -> None:
    store.upsert_snapshot(conn, "2026-11-04", 1, _hits(3))
    url_id = conn.execute("SELECT id FROM urls LIMIT 1").fetchone()["id"]
    store.upsert_page(conn, url_id, {"method": "snippet", "text_hash": "h1", "text_len": 10})
    store.upsert_label(
        conn, url_id, {"prompt_version": "v1", "text_hash": "h1", "site_type": "other", "relevant": 0}
    )
    store.upsert_label(
        conn,
        url_id,
        {"prompt_version": "v1", "text_hash": "h2", "site_type": "review_affiliate", "relevant": 1},
    )
    row = conn.execute("SELECT * FROM v_latest WHERE url_id = ?", (url_id,)).fetchone()
    assert row["site_type"] == "review_affiliate" and row["method"] == "snippet"
    assert store.get_label(conn, url_id, "v1", "h1") is not None
    assert store.get_label(conn, url_id, "v2", "h1") is None


def test_runs_lifecycle(conn) -> None:
    run_id = store.start_run(conn, "2026-11-04", "offline", None)
    store.finish_run(conn, run_id, "partial", {"serp_calls": 9, "cost_usd": 0.5}, [{"stage": "serp"}])
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "partial" and row["serp_calls"] == 9 and row["finished_at"]
    assert '"stage": "serp"' in row["errors_json"]

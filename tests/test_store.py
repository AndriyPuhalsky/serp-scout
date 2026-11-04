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


def test_google_redirects_unwrap_to_target() -> None:
    target = "https://www.casino.ca/best/?b=1"
    goto = "https://www.google.ca/goto?url=https%3A%2F%2Fwww.casino.ca%2Fbest%2F%3Fb%3D1%26utm_source%3Dg&x=1"
    assert normalize_url(goto) == target
    assert normalize_url("https://www.google.com/url?q=https://www.casino.ca/best/?b=1&sa=U") == target
    assert normalize_url("https://google.co.uk/url?url=https://www.casino.ca/best/?b=1") == target
    assert domain_of(goto) == "casino.ca" and url_key(goto) == url_key(target)
    # звичайні сторінки Google і редиректи без цілі — без змін
    assert normalize_url("https://www.google.ca/search?q=casino") == "https://www.google.ca/search?q=casino"
    assert normalize_url("https://www.google.ca/goto?x=1") == "https://www.google.ca/goto?x=1"
    assert normalize_url("https://notgoogle.ca/goto?url=https://a.ca/").startswith(
        "https://notgoogle.ca/goto?url="
    )


def test_google_redirect_and_direct_url_share_one_urls_row(conn) -> None:
    store.upsert_snapshot(conn, "2026-11-04", 1, [SerpHit(1, "https://www.casino.ca/", "t", "s")])
    store.upsert_snapshot(
        conn, "2026-11-04", 2, [SerpHit(1, "https://www.google.ca/goto?url=https://www.casino.ca/", "t", "s")]
    )
    assert store.count(conn, "urls") == 1
    assert conn.execute("SELECT domain FROM urls").fetchone()["domain"] == "casino.ca"


def test_goto_url_domain_from_final_url_key_unchanged(conn) -> None:
    goto = "https://www.google.ca/goto?url=CAESmwEB6zsw"
    store.upsert_snapshot(conn, "2026-11-04", 1, [SerpHit(3, goto, "t", "s")])
    row = conn.execute("SELECT id, url, domain FROM urls").fetchone()
    assert row["domain"] == "google.ca"  # непрозорий goto офлайн не розгортається
    store.upsert_page(conn, row["id"], {"method": "httpx", "text_hash": "h", "text_len": 1})
    final = "https://www.durhampost.ca/top-online-casino-sites-in-canada"
    assert store.apply_final_url(conn, row["id"], final)
    after = conn.execute("SELECT url, domain FROM urls WHERE id = ?", (row["id"],)).fetchone()
    assert after["domain"] == "durhampost.ca"
    assert after["url"] == row["url"] and url_key(after["url"]) == url_key(goto)
    page = store.get_page(conn, row["id"])
    assert page["final_url"] == final
    assert store.google_redirect_urls(conn) == []
    # повтор і звичайний (не Google) URL — без змін
    assert not store.apply_final_url(conn, row["id"], final)
    store.upsert_snapshot(conn, "2026-11-04", 2, [SerpHit(1, "https://casino.ca/", "t", "s")])
    plain = conn.execute("SELECT id FROM urls WHERE url = 'https://casino.ca/'").fetchone()["id"]
    assert not store.apply_final_url(conn, plain, "https://other.ca/")

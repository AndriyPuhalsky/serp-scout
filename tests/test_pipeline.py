"""Повний офлайн-прогін у тимчасовій теці: статус, ідемпотентність, report.json, часткові збої, CLI.

Очікувані числа обчислюються з фікстур `tests/fixtures/serp/*.json` (реальна видача), а не зашиті.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from serp_scout import pipeline, store
from serp_scout.cli import app
from serp_scout.config import Keyword
from serp_scout.labeler import BudgetExceeded, Labeler
from serp_scout.providers.base import SerpError
from serp_scout.providers.fixture import FixtureProvider
from serp_scout.urlnorm import normalize_url

FIXTURES = Path(__file__).parent / "fixtures"
REPORT_KEYS = {"generated_at", "run_dates", "latest_run", "kpi", "keywords", "rows", "brands_top", "runs"}
ROW_KEYS = {
    "url", "domain", "site_type", "relevant", "confidence", "reason", "brands", "contact",
    "placement_signals", "positions", "best_position", "needs_review", "method",
}  # fmt: skip
CONTACT_KEYS = {"email", "contact_page", "telegram", "form", "other"}


def _fixture_hits() -> dict[int, list[str]]:
    """keyword_id → нормалізовані URL органічних результатів із фікстур."""
    hits: dict[int, list[str]] = {}
    for path in (FIXTURES / "serp").glob("*.json"):
        results = json.loads(path.read_text(encoding="utf-8")).get("organic_results", [])
        hits[int(path.stem)] = [
            normalize_url(r["link"]) for r in results if r.get("link", "").startswith("http")
        ]
    return hits


HITS = _fixture_hits()
N_RESULTS = sum(len(v) for v in HITS.values())
N_URLS = len({u for urls in HITS.values() for u in urls})
FIRST_URL = HITS[1][0]


def _counts(settings) -> tuple[int, int, int]:
    conn = store.connect(settings.paths.db)
    try:
        return store.count(conn, "serp_results"), store.count(conn, "urls"), store.count(conn, "labels")
    finally:
        conn.close()


def test_offline_run_ok_and_idempotent(settings) -> None:
    first = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert first.status == "ok" and first.serp_calls == 10 and first.errors == []
    assert first.urls_total == N_URLS and first.urls_new == N_URLS and first.labels_new == N_URLS
    assert _counts(settings) == (N_RESULTS, N_URLS, N_URLS)
    assert first.report and first.report.exists()
    assert {p.name for p in first.exports} == {
        "serp_2026-11-04.csv",
        "labels.csv",
        "history.csv",
        "summary.txt",
    }

    report = json.loads(first.report.read_text(encoding="utf-8"))
    assert REPORT_KEYS <= set(report)
    assert report["kpi"]["urls"] == N_URLS and report["kpi"]["keywords"] == 10
    assert report["latest_run"]["status"] == "ok" and report["run_dates"] == ["2026-11-04"]
    assert len(report["rows"]) == N_URLS and ROW_KEYS <= set(report["rows"][0])
    assert report["rows"][0]["relevant"] is True  # релевантні — першими
    assert len({r["site_type"] for r in report["rows"]}) >= 3
    assert report["brands_top"][0]["pages"] >= 1

    second = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert second.status == "ok" and second.urls_new == 0
    assert second.labels_new == 0 and second.labels_cached == N_URLS
    assert _counts(settings) == (N_RESULTS, N_URLS, N_URLS)


def test_other_date_extends_history(settings) -> None:
    pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-05")
    assert summary.urls_new == 0 and _counts(settings) == (2 * N_RESULTS, N_URLS, N_URLS)
    report = json.loads(summary.report.read_text(encoding="utf-8"))
    assert report["run_dates"] == ["2026-11-04", "2026-11-05"]
    row = next(r for r in report["rows"] if r["url"] == FIRST_URL)
    assert [p["date"] for p in row["positions"]["1"]] == ["2026-11-04", "2026-11-05"]
    assert row["positions"]["1"][0]["position"] == 1


def test_limit_restricts_pages_and_labels(settings) -> None:
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04", limit=5)
    assert summary.urls_total == N_URLS and summary.pages_fetched == 5 and summary.labels_new == 5


def test_serp_failure_for_one_keyword_is_partial(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    original = FixtureProvider.search

    def flaky(self, keyword: Keyword):
        if keyword.id == 3:
            raise SerpError("SerpApi HTTP 500 api_key=secret-key-123456")
        return original(self, keyword)

    monkeypatch.setattr(FixtureProvider, "search", flaky)
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert summary.status == "partial" and summary.serp_calls == 9
    assert (
        summary.errors[0]["stage"] == "serp" and summary.errors[0]["subject"] == "best online casino canada"
    )
    assert "secret-key-123456" not in summary.errors[0]["error"]
    conn = store.connect(settings.paths.db)
    run = conn.execute("SELECT status, errors_json FROM runs").fetchone()
    assert run["status"] == "partial" and "serp" in run["errors_json"]


def test_all_serp_failed_is_failed(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FixtureProvider, "search", lambda self, kw: (_ for _ in ()).throw(SerpError("down")))
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert summary.status == "failed" and summary.serp_calls == 0 and len(summary.errors) == 10


def test_budget_exceeded_keeps_done_work(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Labeler.label
    state = {"n": 0}

    def limited(self, inp):
        state["n"] += 1
        if state["n"] > 3:
            raise BudgetExceeded("бюджет LLM вичерпано: $3.0000 ≥ $3.00")
        return original(self, inp)

    monkeypatch.setattr(Labeler, "label", limited)
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert summary.status == "budget_exceeded" and summary.labels_new == 3
    assert _counts(settings)[2] == 3
    assert summary.errors[-1]["subject"] == "budget"


def test_page_failure_recorded_not_fatal(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    original = pipeline.extract_page

    def broken(html_or_text, **kwargs):
        if kwargs["base_url"] == FIRST_URL:
            raise RuntimeError("парсер впав")
        return original(html_or_text, **kwargs)

    monkeypatch.setattr(pipeline, "extract_page", broken)
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert summary.status == "partial" and summary.labels_new == N_URLS - 1
    assert sum(1 for e in summary.errors if e["stage"] == "page") == 1
    conn = store.connect(settings.paths.db)
    row = conn.execute(
        "SELECT error FROM pages p JOIN urls u ON u.id = p.url_id WHERE u.url = ?", (FIRST_URL,)
    ).fetchone()
    assert row["error"] and "парсер" in row["error"]


def test_no_llm_and_limit_zero_for_fixture_capture(settings) -> None:
    only_serp = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04", limit=0)
    assert only_serp.status == "ok" and only_serp.serp_calls == 10
    assert only_serp.pages_fetched == 0 and only_serp.labels_new == 0
    no_llm = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04", no_llm=True)
    assert no_llm.status == "ok" and no_llm.pages_fetched == N_URLS and no_llm.labels_new == 0
    report = json.loads(no_llm.report.read_text(encoding="utf-8"))
    row = report["rows"][0]
    assert row["contact"] is None and row["site_type"] is None
    assert row["method"] in ("httpx", "reader", "snippet")


def test_report_contract_for_frontend(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    original = FixtureProvider.search
    monkeypatch.setattr(
        FixtureProvider,
        "search",
        lambda self, kw: (_ for _ in ()).throw(SerpError("boom")) if kw.id == 2 else original(self, kw),
    )
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    report = json.loads(summary.report.read_text(encoding="utf-8"))
    assert 0 <= report["kpi"]["relevant_pct"] <= 100
    assert all(isinstance(e, str) for e in report["latest_run"]["errors"]) and report["latest_run"]["errors"]
    rows = report["rows"]
    labeled = [r for r in rows if r["site_type"]]
    assert labeled and all(0 <= r["confidence"] <= 1 for r in labeled)
    with_contact = [r for r in rows if r["contact"] is not None]
    assert with_contact, "у реальній розмітці має бути хоч один контакт"
    assert all(
        set(r["contact"]) == CONTACT_KEYS and isinstance(r["contact"]["form"], bool) for r in with_contact
    )
    with_brands = [r for r in rows if r["brands"]]
    assert with_brands and all(isinstance(b, str) for r in with_brands for b in r["brands"])
    first = next(r for r in rows if r["url"] == FIRST_URL)
    assert all(k.isdigit() for k in first["positions"]) and first["positions"]["1"][0]["position"] == 1
    assert {r["method"] for r in rows} <= {"httpx", "reader", "snippet"}
    datetime.fromisoformat(report["generated_at"])


def test_cli_run_offline_and_stats(settings) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--offline", "--date", "2026-11-04", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "SERP-виклики" in result.output and "ok" in result.output
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0 and "2026-11-04" in result.output
    result = runner.invoke(app, ["labels", "--limit", "2"])
    assert result.exit_code == 0 and "Розмітка" in result.output
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0 and "summary.txt" in result.output
    result = runner.invoke(app, ["build-site"])
    assert result.exit_code == 0 and "report.json" in result.output


def test_cli_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "export", "build-site", "labels", "stats"):
        assert command in result.output


def test_llm_exception_for_one_url_is_partial(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Виняток Anthropic по одному URL → partial, stage `llm` у errors_json, решта розмічена."""
    import anthropic
    import httpx2

    original = Labeler.label

    def flaky(self, inp):
        if inp.url == FIRST_URL:
            request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIStatusError(
                "overloaded", response=httpx2.Response(529, request=request), body=None
            )
        return original(self, inp)

    monkeypatch.setattr(Labeler, "label", flaky)
    summary = pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    assert summary.status == "partial" and summary.labels_new == N_URLS - 1
    llm_errors = [e for e in summary.errors if e["stage"] == "llm"]
    assert len(llm_errors) == 1 and llm_errors[0]["subject"] == FIRST_URL
    assert "APIStatusError" in llm_errors[0]["error"]
    conn = store.connect(settings.paths.db)
    run = conn.execute("SELECT status, errors_json FROM runs").fetchone()
    errors = json.loads(run["errors_json"])
    assert run["status"] == "partial" and errors[0]["stage"] == "llm"
    assert _counts(settings)[2] == N_URLS - 1


def test_cli_labels_sample_and_url(settings) -> None:
    pipeline.run_pipeline(settings, offline=True, run_date="2026-11-04")
    runner = CliRunner()
    first = runner.invoke(app, ["labels", "--sample", "5", "--seed", "7", "--json"])
    assert first.exit_code == 0, first.output
    rows = json.loads(first.output)
    assert len(rows) == 5 and all(r["site_type"] for r in rows)
    assert {"url", "site_type", "relevant", "confidence", "reason", "brands", "contact"} <= set(rows[0])
    again = runner.invoke(app, ["labels", "--sample", "5", "--seed", "7", "--json"])
    assert [r["url"] for r in json.loads(again.output)] == [r["url"] for r in rows]  # детерміновано
    other = runner.invoke(app, ["labels", "--sample", "5", "--seed", "8", "--json"])
    assert {r["url"] for r in json.loads(other.output)} != {r["url"] for r in rows}
    one = runner.invoke(app, ["labels", "--url", FIRST_URL, "--json"])
    assert one.exit_code == 0 and json.loads(one.output)[0]["url"] == FIRST_URL
    assert len(json.loads(one.output)) == 1
    missing = runner.invoke(app, ["labels", "--url", "https://nope.example/none"])
    assert missing.exit_code == 1
    table = runner.invoke(app, ["labels", "--sample", "3"])
    assert table.exit_code == 0 and "вибірка 3" in table.output

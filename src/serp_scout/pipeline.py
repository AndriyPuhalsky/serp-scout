"""Оркестрація одного прогону: SERP → снапшот → сторінки → розмітка → експорт → report.json.

Збій одного ключа або URL не валить прогін: помилка потрапляє в `pages.error` / `runs.errors_json`,
статус стає `partial`. Вичерпання бюджету LLM → `budget_exceeded`, усе зроблене збережено.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from serp_scout import store
from serp_scout.brands import BrandLexicon
from serp_scout.config import Settings, mask_secrets
from serp_scout.costs import append_cost
from serp_scout.export import export_all
from serp_scout.extract import extract_page
from serp_scout.fetch import FetchResult, PageFetcher
from serp_scout.labeler import BudgetExceeded, Labeler, LabelInput
from serp_scout.providers.fixture import FixtureProvider
from serp_scout.providers.serpapi import SerpApiProvider
from serp_scout.runinfo import RunSummary, git_sha, record_error, today_utc
from serp_scout.site_build import write_report
from serp_scout.urlnorm import url_key

Progress = Callable[[str], None]


def _offline_fetch(settings: Settings, url: str, title: str, snippet: str) -> FetchResult:
    """У `--offline` мережі немає: фікстура сторінки з `tests/fixtures/pages/` або сніпет.

    `<url_key>.html` — сирий HTML (метод httpx); `<url_key>.<httpx|reader>.txt` — уже витягнутий текст
    реального прогону з методом у назві; інакше `method=snippet`.
    """
    pages_dir = settings.paths.fixtures_dir / "pages"
    key = url_key(url)
    html_path = pages_dir / f"{key}.html"
    if html_path.exists():
        return FetchResult("httpx", 200, html_path.read_text(encoding="utf-8"))
    for method in ("httpx", "reader"):
        text_path = pages_dir / f"{key}.{method}.txt"
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8")
            return FetchResult(method, 200, text, None, text)
    fallback = "\n\n".join(part for part in (title, snippet) if part)
    return FetchResult("snippet", None, fallback, "offline: фікстури сторінки немає", fallback)


def _stage_serp(settings: Settings, conn, summary: RunSummary, offline: bool, progress: Progress) -> None:
    if offline or settings.serp.provider == "fixture":
        provider = FixtureProvider(settings.paths.fixtures_dir / "serp", settings.serp.num)
    else:
        provider = SerpApiProvider(settings.serp, settings.paths.raw_dir, summary.run_date)
    for kw in settings.keywords:
        try:
            hits = provider.search(kw)
            summary.serp_calls += 1
            summary.urls_new += store.upsert_snapshot(conn, summary.run_date, kw.id, hits)
            progress(f"SERP «{kw.keyword}»: {len(hits)} результатів")
        except Exception as exc:  # noqa: BLE001 - один ключ не валить решту
            record_error(summary, "serp", kw.keyword, exc)
            progress(f"SERP «{kw.keyword}»: збій — {mask_secrets(str(exc))}")


def _stage_pages(
    settings: Settings,
    conn,
    summary: RunSummary,
    rows: list,
    offline: bool,
    refetch: bool,
    progress: Progress,
) -> None:
    todo = [r for r in rows if refetch or store.get_page(conn, r["url_id"]) is None]
    if not todo:
        return
    pages_dir = settings.paths.raw_dir / summary.run_date / "pages"
    if offline:
        results = {
            r["url"]: _offline_fetch(settings, r["url"], r["title"] or "", r["snippet"] or "") for r in todo
        }
    else:
        results = PageFetcher(settings.fetch).fetch_many(
            [(r["url"], r["title"] or "", r["snippet"] or "") for r in todo]
        )
    for r in todo:
        res = results[r["url"]]
        try:
            page = extract_page(
                res.html_or_text,
                is_html=res.is_html,
                base_url=r["url"],
                head=settings.fetch.text_head_chars,
                tail=settings.fetch.text_tail_chars,
                prefetched_text=res.text if res.is_html else None,
            )
            pages_dir.mkdir(parents=True, exist_ok=True)
            text_path = pages_dir / f"{r['url_id']}.txt"
            text_path.write_text(page.text, encoding="utf-8")
            store.upsert_page(
                conn,
                r["url_id"],
                {
                    "fetched_at": store.now_iso(),
                    "method": res.method,
                    "http_status": res.http_status,
                    "text_hash": page.text_hash,
                    "text_len": page.text_len,
                    "text_path": str(text_path.relative_to(settings.paths.data_dir)),
                    "emails_json": json.dumps(page.emails),
                    "contact_links_json": json.dumps(page.contact_links),
                    "error": res.error,
                },
            )
            summary.pages_fetched += 1
            if res.method == "snippet":
                summary.pages_failed += 1
        except Exception as exc:  # noqa: BLE001
            summary.pages_failed += 1
            record_error(summary, "page", r["url"], exc)
            store.upsert_page(
                conn,
                r["url_id"],
                {
                    "fetched_at": store.now_iso(),
                    "method": res.method,
                    "http_status": res.http_status,
                    "error": mask_secrets(str(exc))[:300],
                },
            )
    progress(f"Сторінки: {summary.pages_fetched} оброблено, {summary.pages_failed} без тексту/зі збоєм")


def _stage_labels(
    settings: Settings,
    conn,
    summary: RunSummary,
    rows: list,
    offline: bool,
    relabel: bool,
    progress: Progress,
) -> bool:
    """Повертає True, якщо прогін зупинено бюджетом."""
    lexicon = BrandLexicon.from_config(settings.brands)
    labeler = Labeler(
        settings.llm,
        offline=offline,
        cassette_dir=settings.paths.fixtures_dir / "llm",
        brand_finder=lexicon.find_in_text,
    )
    version = settings.llm.prompt_version
    for r in rows:
        page = store.get_page(conn, r["url_id"])
        if page is None or not page["text_hash"]:
            continue
        if not relabel and store.get_label(conn, r["url_id"], version, page["text_hash"]) is not None:
            summary.labels_cached += 1
            continue
        text_path = settings.paths.data_dir / (page["text_path"] or "")
        text = text_path.read_text(encoding="utf-8") if page["text_path"] and text_path.exists() else ""
        inp = LabelInput(
            url=r["url"],
            domain=r["domain"],
            keywords=r["keywords"] or "",
            title=r["title"] or "",
            snippet=r["snippet"] or "",
            method=page["method"] or "snippet",
            text=text,
            emails=json.loads(page["emails_json"] or "[]"),
            contact_links=json.loads(page["contact_links_json"] or "[]"),
        )
        try:
            result = labeler.label(inp)
        except BudgetExceeded as exc:
            summary.errors.append({"stage": "llm", "subject": "budget", "error": str(exc)})
            progress(str(exc))
            return True
        except Exception as exc:  # noqa: BLE001
            record_error(summary, "llm", r["url"], exc)
            continue
        label = result.label
        brands = lexicon.merge([b.normalized or b.name for b in label.brands_mentioned], text)
        store.upsert_label(
            conn,
            r["url_id"],
            {
                "prompt_version": version,
                "text_hash": page["text_hash"],
                "site_type": label.site_type,
                "relevant": int(label.relevant_for_placement),
                "confidence": label.confidence,
                "reason": label.reason,
                "brands_json": json.dumps(brands, ensure_ascii=False),
                "contact_json": label.contact.model_dump_json(),
                "placement_signals_json": json.dumps(label.placement_signals),
                "needs_review": int(result.needs_review),
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": result.cost_usd,
                "labeled_at": store.now_iso(),
            },
        )
        summary.labels_new += 1
        summary.input_tokens += result.input_tokens
        summary.output_tokens += result.output_tokens
        summary.cost_usd += result.cost_usd
        if not result.stub:
            append_cost(
                settings.paths.costs,
                summary.run_date,
                r["url_id"],
                result.model,
                result.input_tokens,
                result.output_tokens,
                result.cost_usd,
            )
    progress(f"Розмітка: {summary.labels_new} нових, {summary.labels_cached} з кешу, ${summary.cost_usd:.4f}")
    return False


def run_pipeline(
    settings: Settings,
    *,
    offline: bool = False,
    limit: int | None = None,
    run_date: str | None = None,
    relabel: bool = False,
    no_llm: bool = False,
    refetch: bool = False,
    progress: Progress | None = None,
) -> RunSummary:
    """Повний прогін; завжди закриває рядок `runs` і повертає підсумок.

    `limit=0` — лише SERP (без сторінок і LLM, для зняття фікстур); `no_llm` — сторінки без розмітки.
    """
    progress = progress or (lambda _msg: None)
    run_date = run_date or today_utc()
    conn = store.connect(settings.paths.db)
    store.init_db(conn)
    store.upsert_keywords(conn, settings.keywords)
    mode = "offline" if offline else "live"
    summary = RunSummary(
        run_id=store.start_run(conn, run_date, mode, git_sha(settings.paths.root)),
        run_date=run_date,
        mode=mode,
    )
    budget_stop = False
    try:
        _stage_serp(settings, conn, summary, offline, progress)
        rows = store.snapshot_urls(conn, run_date)
        summary.urls_total = len(rows)
        if limit is not None:
            rows = rows[: max(0, limit)]
        _stage_pages(settings, conn, summary, rows, offline, refetch, progress)
        if no_llm:
            progress("Розмітку пропущено (--no-llm)")
        else:
            budget_stop = _stage_labels(settings, conn, summary, rows, offline, relabel, progress)
    except Exception as exc:  # noqa: BLE001 - несподіваний збій етапу: фіксуємо і закриваємо прогін
        record_error(summary, "pipeline", "run", exc)
    if budget_stop:
        summary.status = "budget_exceeded"
    elif summary.serp_calls == 0 and settings.keywords:
        summary.status = "failed"
    elif summary.errors:
        summary.status = "partial"
    else:
        summary.status = "ok"
    store.finish_run(conn, summary.run_id, summary.status, summary.counters(), summary.errors)
    try:
        summary.exports = export_all(conn, settings.paths.export_dir, run_date)
        summary.report = write_report(conn, settings.keywords, settings.paths.report)
    except Exception as exc:  # noqa: BLE001
        record_error(summary, "export", "files", exc)
        store.finish_run(conn, summary.run_id, summary.status, summary.counters(), summary.errors)
    conn.close()
    return summary

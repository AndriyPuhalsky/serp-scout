"""CLI serp-scout (typer): run · export · build-site · labels · stats."""

from __future__ import annotations

import json
import random
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from serp_scout import store
from serp_scout.config import load_settings
from serp_scout.costs import summarize
from serp_scout.export import export_all
from serp_scout.pipeline import RunSummary, run_pipeline
from serp_scout.site_build import write_report
from serp_scout.urlnorm import normalize_url

app = typer.Typer(
    help="serp-scout — топ-10 Google (mobile, Канада) → SQLite → розмітка LLM → звіт.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_STATUS_STYLE = {"ok": "green", "partial": "yellow", "budget_exceeded": "yellow", "failed": "red"}


def print_summary(summary: RunSummary) -> None:
    """Підсумок прогону у вигляді таблиці rich."""
    table = Table(title=f"Прогін {summary.run_date} ({summary.mode})", show_header=False)
    table.add_column("Показник", style="bold")
    table.add_column("Значення", justify="right")
    table.add_row("SERP-виклики", str(summary.serp_calls))
    table.add_row("URL усього / нових", f"{summary.urls_total} / {summary.urls_new}")
    table.add_row("Сторінок оброблено / без тексту", f"{summary.pages_fetched} / {summary.pages_failed}")
    table.add_row("LLM-викликів нових / з кешу", f"{summary.labels_new} / {summary.labels_cached}")
    table.add_row("Токени вхід / вихід", f"{summary.input_tokens} / {summary.output_tokens}")
    table.add_row("Вартість прогону", f"${summary.cost_usd:.4f}")
    table.add_row("Помилок", str(len(summary.errors)))
    table.add_row("Статус", f"[{_STATUS_STYLE.get(summary.status, 'white')}]{summary.status}[/]")
    console.print(table)
    for err in summary.errors[:10]:
        console.print(f"  [dim]• {err['stage']} · {err['subject']}: {err['error']}[/]")
    if summary.report:
        console.print(f"report.json → {summary.report}")


@app.command()
def run(
    offline: Annotated[
        bool, typer.Option("--offline", help="Фікстури SerpApi і касети LLM, без ключів і мережі")
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Обробити лише перші N URL (сторінки + LLM)")
    ] = None,
    date: Annotated[
        str | None, typer.Option("--date", help="Дата снапшота YYYY-MM-DD (типово — сьогодні UTC)")
    ] = None,
    relabel: Annotated[
        bool, typer.Option("--relabel", help="Перерозмітити навіть за наявності кешу")
    ] = False,
    refetch: Annotated[bool, typer.Option("--refetch", help="Перезавантажити сторінки, що вже є")] = False,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Без розмітки LLM (лише SERP і сторінки)")] = False,
) -> None:
    """Повний прогін: SERP → сховище → сторінки → розмітка → експорт → report.json.

    `--offline` пише в `data/demo/` і `site/data/report.demo.json` (реальний дамп не чіпається);
    `--limit 0` — лише SERP, без сторінок і LLM (зняти реальні фікстури).
    """
    settings = load_settings(demo=offline)
    summary = run_pipeline(
        settings,
        offline=offline,
        limit=limit,
        run_date=date,
        relabel=relabel,
        refetch=refetch,
        no_llm=no_llm,
        progress=lambda msg: console.print(f"[dim]{msg}[/]"),
    )
    print_summary(summary)
    if offline and summary.report:
        console.print(f"Перегляд демо: make serve → http://127.0.0.1:8765/?data=data/{summary.report.name}")
    if summary.status == "failed":
        raise typer.Exit(code=1)


DemoOption = Annotated[bool, typer.Option("--demo", help="Працювати з демо-даними data/demo (офлайн-прогін)")]


@app.command()
def export(
    date: Annotated[str | None, typer.Option("--date", help="Дата снапшота; типово — останній")] = None,
    demo: DemoOption = False,
) -> None:
    """CSV (serp_<дата>, labels, history) і summary.txt у data/export."""
    settings = load_settings(demo=demo)
    conn = store.connect(settings.paths.db)
    store.init_db(conn)
    paths = export_all(conn, settings.paths.export_dir, date)
    if not paths:
        console.print("[yellow]У БД ще немає снапшотів — спершу `serp-scout run`.[/]")
        raise typer.Exit(code=1)
    for p in paths:
        console.print(f"→ {p}")


@app.command("build-site")
def build_site(demo: DemoOption = False) -> None:
    """Зібрати site/data/report.json для сайту-звіту."""
    settings = load_settings(demo=demo)
    conn = store.connect(settings.paths.db)
    store.init_db(conn)
    path = write_report(conn, settings.keywords, settings.paths.report)
    console.print(f"report.json → {path}")


def _label_rows(
    conn, run_date: str, *, url: str | None, relevant_only: bool, sample: int | None, seed: int, limit: int
) -> list[dict]:
    """Рядки останньої розмітки снапшота як словники; фільтр за URL, випадкова вибірка, ліміт."""
    query = (
        "SELECT * FROM v_latest WHERE run_date = ? GROUP BY url_id ORDER BY relevant DESC, confidence DESC"
    )
    rows = []
    for r in conn.execute(query, (run_date,)).fetchall():
        if url and r["url"] != normalize_url(url):
            continue
        if relevant_only and not r["relevant"]:
            continue
        contact = json.loads(r["contact_json"]) if r["contact_json"] else None
        rows.append(
            {
                "url": r["url"], "domain": r["domain"], "keyword": r["keyword"], "title": r["title"],
                "snippet": r["snippet"], "site_type": r["site_type"],
                "relevant": bool(r["relevant"]) if r["relevant"] is not None else None,
                "confidence": r["confidence"], "reason": r["reason"],
                "brands": json.loads(r["brands_json"] or "[]"), "contact": contact,
                "placement_signals": json.loads(r["placement_signals_json"] or "[]"),
                "needs_review": bool(r["needs_review"]) if r["needs_review"] is not None else None,
                "model": r["model"], "method": r["method"], "labeled_at": r["labeled_at"],
            }
        )  # fmt: skip
    if sample is not None:
        labeled = [r for r in rows if r["site_type"]]
        rows = random.Random(seed).sample(labeled, min(sample, len(labeled)))
        return rows
    return rows[:limit]


@app.command()
def labels(
    limit: Annotated[int, typer.Option("--limit", help="Скільки рядків показати")] = 30,
    relevant_only: Annotated[bool, typer.Option("--relevant", help="Лише релевантні для розміщення")] = False,
    url: Annotated[str | None, typer.Option("--url", help="Показати розмітку одного URL")] = None,
    sample: Annotated[
        int | None, typer.Option("--sample", help="Випадкова вибірка N розмічених URL (для судді)")
    ] = None,
    seed: Annotated[int, typer.Option("--seed", help="Зерно випадковості для --sample")] = 42,
    as_json: Annotated[bool, typer.Option("--json", help="Вивести JSON замість таблиці")] = False,
    demo: DemoOption = False,
) -> None:
    """Показати останню розмітку URL (тип, релевантність, впевненість, бренди, контакт)."""
    settings = load_settings(demo=demo)
    conn = store.connect(settings.paths.db)
    store.init_db(conn)
    run_date = store.latest_run_date(conn)
    if run_date is None:
        console.print("[yellow]Розмітки ще немає.[/]")
        raise typer.Exit(code=1)
    rows = _label_rows(
        conn, run_date, url=url, relevant_only=relevant_only, sample=sample, seed=seed, limit=limit
    )
    if url and not rows:
        console.print(f"[yellow]URL не знайдено в останньому снапшоті: {url}[/]")
        raise typer.Exit(code=1)
    if as_json:
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    table = Table(
        title=f"Розмітка за {run_date}" + (f" · вибірка {len(rows)} (seed {seed})" if sample else "")
    )
    for col in ("Домен", "Тип", "Рел.", "Впевн.", "Бренди", "Контакт", "Чому"):
        table.add_column(col, overflow="fold")
    for r in rows:
        contact = r["contact"] or {}
        table.add_row(
            r["domain"],
            r["site_type"] or "—",
            "так" if r["relevant"] else "ні",
            f"{(r['confidence'] or 0):.2f}",
            ", ".join(r["brands"][:4]) or "—",
            contact.get("email") or contact.get("contact_page") or "—",
            (r["reason"] or "")[:90],
        )
    console.print(table)


@app.command()
def stats(demo: DemoOption = False) -> None:
    """Таблиця прогонів і сумарна вартість LLM."""
    settings = load_settings(demo=demo)
    conn = store.connect(settings.paths.db)
    store.init_db(conn)
    table = Table(title="Прогони")
    for col in ("Дата", "Режим", "Статус", "SERP", "URL", "Нових", "LLM", "Токени", "$", "Помилок"):
        is_text = col in ("Дата", "Режим", "Статус")
        table.add_column(col, justify="left" if is_text else "right", no_wrap=is_text)
    total = 0.0
    for r in conn.execute("SELECT * FROM runs ORDER BY id").fetchall():
        errors = len(json.loads(r["errors_json"] or "[]"))
        total += float(r["cost_usd"] or 0)
        table.add_row(
            r["run_date"],
            r["mode"] or "—",
            r["status"],
            str(r["serp_calls"]),
            str(r["urls_total"]),
            str(r["urls_new"]),
            str(r["labels_new"]),
            f"{r['input_tokens']}/{r['output_tokens']}",
            f"{float(r['cost_usd'] or 0):.4f}",
            str(errors),
        )
    console.print(table)
    costs = summarize(settings.paths.costs)["total"]
    console.print(
        f"Разом за runs: ${total:.4f} · за costs.jsonl: ${costs['cost_usd']:.4f} ({costs['calls']} викликів)"
    )


if __name__ == "__main__":  # pragma: no cover
    app()

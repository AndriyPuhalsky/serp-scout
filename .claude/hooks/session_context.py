#!/usr/bin/env python3
"""SessionStart-хук: підтягує в контекст стан проєкту на момент старту сесії.

Виводить: статус проєкту (здано, режим супроводу), поточну ітерацію (CLAUDE.md) з чеклістом із docs/05,
заголовки останніх записів журналу й останній запис, наявність ключів у .env
(ЛИШЕ назви змінних — значення ніколи не друкуються), чи є сьогоднішній снапшот
SERP (data/raw/<дата>/ або рядок у runs) і сумарні витрати LLM (data/costs.jsonl).
Кожен блок рахується окремо і не валить решту; невалідний вхід → вихід 0.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import sys

SUBMITTED = "2026-11-04"  # тестове здано; дедлайну більше немає — режим супроводу
TZ = "Europe/Kyiv"
EXPECTED_ENV = ("SERPAPI_KEY", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "LLM_BUDGET_USD")
LAST_ENTRY_MAX = 2000


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def now_kyiv():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(TZ))
    except Exception:  # noqa: BLE001 — без tzdata працюємо за локальним часом
        return dt.datetime.now()


def status_line(now):
    """Здано, далі супровід: скільки днів проєкт на підтримці (без таймера дедлайну)."""
    submitted = dt.date.fromisoformat(SUBMITTED)
    days = (now.date() - submitted).days
    return f"Здано {SUBMITTED}, режим супроводу ({days} дн.), дедлайну немає."


def current_iteration(root):
    """Рядок із ▶ з розділу «## Поточна ітерація» CLAUDE.md і номер ітерації (або None)."""
    m = re.search(r"(?ms)^## Поточна ітерація\s*\n(.+?)(?=^## |\Z)", read(os.path.join(root, "CLAUDE.md")))
    if not m:
        return "(розділ «Поточна ітерація» не знайдено)", None
    line = next((ln.strip() for ln in m.group(1).splitlines() if "▶" in ln), None)
    if not line:
        return "(у розділі «Поточна ітерація» немає рядка з ▶)", None
    num = re.search(r"[ІI](\d+)", line)
    return line, (num.group(1) if num else None)


def checklist(root):
    """Чекліст із блоку «## ▶ ІN — …» у docs/05: (зроблено, усього, рядки)."""
    text = read(os.path.join(root, "docs", "05_КАРТА_ІТЕРАЦІЙ.md"))
    m = re.search(r"(?ms)^## ▶ .*?\n(.*?)(?=^## |\Z)", text)
    if not m:
        return None
    items = [ln.rstrip() for ln in m.group(1).splitlines() if re.match(r"\s*- \[[ xX]\]", ln)]
    done = sum(1 for ln in items if re.match(r"\s*- \[[xX]\]", ln))
    return done, len(items), items


def journal(root):
    entries = re.split(r"(?m)^(?=### #\d+)", read(os.path.join(root, "ЖУРНАЛ_ПОДІЙ.md")))
    entries = [e.strip() for e in entries if e.startswith("### #")]
    titles = "\n".join(e.splitlines()[0] for e in entries[-5:])
    last = entries[-1] if entries else ""
    if len(last) > LAST_ENTRY_MAX:
        last = last[:LAST_ENTRY_MAX].rstrip() + "\n… (запис обрізано, повністю — у ЖУРНАЛ_ПОДІЙ.md)"
    return len(entries), titles, last


def env_status(root):
    """«NAME: задано/порожньо/не задано» — лише назви змінних; зі значення береться лише факт непорожності."""
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return ".env відсутній"
    present = {}
    for line in read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        value = m.group(2).strip().strip('"').strip("'")
        present[m.group(1)] = "задано" if value else "порожньо"
    parts = [f"{name}: {present.get(name, 'не задано')}" for name in EXPECTED_ENV]
    extra = sorted(n for n in present if n not in EXPECTED_ENV)
    if extra:
        parts.append("інші в .env: " + ", ".join(extra))
    return "; ".join(parts)


def snapshot_today(root, today):
    """True, якщо є data/raw/<сьогодні>/ або рядок runs із run_date = сьогодні в data/serp.sqlite."""
    if os.path.isdir(os.path.join(root, "data", "raw", today)):
        return True
    db = os.path.join(root, "data", "serp.sqlite")
    if not os.path.isfile(db):
        return False
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            query = "SELECT COUNT(*) FROM runs WHERE substr(run_date, 1, 10) = ?"
            row = con.execute(query, (today,)).fetchone()
        finally:
            con.close()
        return bool(row and row[0])
    except sqlite3.Error:
        return False


def llm_costs(root):
    path = os.path.join(root, "data", "costs.jsonl")
    if not os.path.isfile(path):
        return "data/costs.jsonl відсутній (витрат LLM ще немає)"
    total, n = 0.0, 0
    for line in read(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line).get("cost_usd")
            total += float(value)
            n += 1
        except (ValueError, TypeError, AttributeError):
            continue
    return f"${total:.4f} за {n} записів у data/costs.jsonl"


def build_context(root):
    now = now_kyiv()
    today = now.strftime("%Y-%m-%d")
    blocks = [f"Проєкт serp-scout. Зараз {now.strftime('%Y-%m-%d %H:%M')} (Київ). {status_line(now)}"]

    line, _ = current_iteration(root)
    blocks.append(f"Поточна ітерація (CLAUDE.md): {line}")
    cl = checklist(root)
    if cl:
        done, total, items = cl
        blocks.append(f"Чекліст ▶-ітерації в docs/05: {done}/{total} зроблено\n" + "\n".join(items))
    else:
        blocks.append("Чекліст: у docs/05 немає блоку «## ▶ …».")

    blocks.append(f"Ключі в .env (лише назви): {env_status(root)}")
    blocks.append(f"Сьогоднішній снапшот SERP ({today}): {'є' if snapshot_today(root, today) else 'немає'}.")
    blocks.append(f"Витрати LLM: {llm_costs(root)}.")

    count, titles, last = journal(root)
    blocks.append(f"Записів у ЖУРНАЛ_ПОДІЙ.md: {count}.\nОстанні записи:\n{titles or '(немає)'}")
    if last:
        blocks.append(f"Останній запис:\n{last}")
    return "\n\n".join(blocks)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    try:
        ctx = build_context(root)
    except Exception as e:  # noqa: BLE001 — контекст не має зривати старт сесії
        ctx = f"session_context: не вдалося зібрати контекст ({type(e).__name__}: {e})"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

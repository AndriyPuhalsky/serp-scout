# 06 — Runbook

## Ключі й змінні (`.env` локально, GitHub Secrets/Variables в Actions)

| Змінна | Де взяти | Навіщо |
|---|---|---|
| `SERPAPI_KEY` | serpapi.com → Sign up → Dashboard → API key (Free, без картки) | топ-10 Google |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys | LLM-розмітка |
| `LLM_BUDGET_USD` | число, типово 3 | стоп-ліміт витрат на прогін (в Actions — Variable) |
| `TELEGRAM_BOT_TOKEN` | @BotFather → /newbot | сповіщення |
| `TELEGRAM_CHAT_ID` | написати боту /start → `curl -s "https://api.telegram.org/bot$TOKEN/getUpdates"` → `message.chat.id` | куди слати |
| `TG_DEV` | `0`/`1` | вимкнути сповіщення харнесу (локально) |

Claude Code `.env` не читає (deny у `.claude/settings.json`); хуки й пайплайн беруть змінні з оточення/файлу самі.

## Локальний запуск

```
cp .env.example .env         # заповнити ключі
make install                 # uv sync --frozen
make demo                    # офлайн на фікстурах, без ключів
make run                     # живий прогін; make run ARGS="--limit 5"
make export && make site     # CSV/JSON і site/data/report.json
make serve                   # http://127.0.0.1:8765
make test && make lint
```

## GitHub Actions

Workflow `daily.yml`: cron 09:00 Київ (+ запасний 10:30), `workflow_dispatch` (`force`, `limit`). Secrets: `SERPAPI_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; Variable: `LLM_BUDGET_USD`. Задати: `gh secret set NAME` (значення з stdin), `gh variable set LLM_BUDGET_USD --body 3`. Ручний запуск: `gh workflow run daily.yml -f force=true`. Логи: `gh run list --workflow daily.yml`, `gh run view <id> --log-failed`.

## Netlify

Netlify → Add new site → Import from Git → репозиторій `serp-scout` → publish dir `site`, build command порожня (є `netlify.toml`). URL сайту: — (заповнити після І4). Деплой — автоматично на push у `main`.

## Домен `google.*` у звіті

Якщо в таблиці з'явився домен `google.ca` (goto-редирект з мобільної видачі): `uv run serp-scout resolve-redirects && make export site` (3 живі GET без LLM, повторний запуск — «Нерозгорнутих редиректів Google немає.»). У щоденному прогоні це робиться автоматично при завантаженні сторінки.

## Інциденти

| Симптом | Причина | Дія |
|---|---|---|
| `SerpError 401` | ключ недійсний/порожній | перевірити `SERPAPI_KEY` у Secrets |
| `SerpError 429` або `runs.status=partial` з помилками по ключах | квота Free вичерпана | зачекати до наступного місяця або Starter; прогін доробить решту ключів завтра |
| `runs.status=budget_exceeded` | перевищено `LLM_BUDGET_USD` | підняти Variable або лишити — наступний прогін доробить нерозмічені URL |
| багато `pages.method=snippet` | сайти за Cloudflare/капчею | очікувано; розмітка з низькою впевненістю і `needs_review` |
| `commit_push.sh` падає на push | конфлікт із ручним пушем | скрипт робить rebase 3 рази; якщо ні — `gh workflow run daily.yml -f force=true` |
| Сайт не оновився | Netlify не побачив push або збірка впала | Netlify → Deploys; перевірити `site/data/report.json` у `main` |
| Telegram мовчить | токен/chat_id або `TG_DEV=0` | `make notify-test`; перевірити Secrets |
| Ключ дає < 10 органічних результатів (напр. «interac casino» — 2) | Google на mobile прибирає результати (`dmca_messages`), `num=20` не допомагає (перевірено 2026-11-04) | це факт видачі, не збій; у звіті ключ має менше рядків |

- **2026-11-04, run 41829818030 (`force=true`):** прогін ok (79 URL, 30 нових, $0.48), коміт бота `98aa5c4` створено, але 3 спроби `git pull --rebase` впали з «cannot pull with rebase: You have unstaged changes». Причина: `data/costs.jsonl` став tracked (коміт 3807fb4), прогін дописує в нього, а `tools/commit_push.sh` його не стейджив. Виправлення: файл додано в `TO_ADD`, `git pull --rebase --autostash`. Симптом у Telegram — ❌ з посиланням на run; діагноз — `gh run view <id> --log-failed`. Дані такого прогону лишаються на раннері (артефакт `raw-<дата>` зберігається 7 днів, мітки — ні), тож після фіксу потрібен повторний прогін.

## Скріншоти для методички (`make guide-shots`, І8)

- `make guide-shots` читає `site/guide/shots.json` і пише `site/guide/img/*.png` з https://serp-scout.netlify.app через headless Chrome і CDP (`tools/guide_shots.mjs`; Node ≥ 22, без npm-залежностей). Шлях до Chrome — `CHROME_BIN`, типово `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`. Локально: `make serve`, потім `make guide-shots ARGS="--base http://127.0.0.1:8765"`. Один знімок: `ARGS="--only 05-"`.
- Запис у `shots.json`: `{out, url, selector?, click?, wait?, scale?, maxHeight?}`; `click` викликає `.click()` у DOM (для `<select>` не підходить), світла тема і `prefers-reduced-motion` емулюються.
- Код виходу 1 — якийсь знімок пропущено (рядок «ПРОПУЩЕНО» з причиною), 2 — немає Chrome або конфігу. PNG понад 200 КБ: менший `maxHeight` або `scale: 0.75`.
- Відома вада: при кліпі по рядку таблиці (`tr`, `td.positions`) після кліку рамка зсувається вниз на ≈ 35–40 px (знімок захоплює сусідній рядок); обхід — брати секцію або окрему комірку (`td.why`, `.sheet` з `maxHeight`). На живому Netlify у знімок потрапляє бейдж «Powered…» (інжектується хостингом, у коді сайту його немає) — знімати з локального `--base http://127.0.0.1:8765`.
- Якщо Chrome лишився після аварійного завершення: `pgrep -fl remote-debugging-port`, потім `pkill -f serp-scout-shots-`. Secrets не потрібні; в Actions не запускається (припущення: лише macOS, перевірено з Node 25 і Chrome 156).

## Після зміни `prompt_version` (касети для `make demo`)

1. Живий прогін з `--relabel` (вартість ≈ $1.4 на 77 URL). 2. `uv run python -m tests.refresh_cassettes` → «Касет записано: 77 (prompt_version=vN)». 3. `make demo ARGS="--refetch --relabel"` — демо-БД кешує мітки за `(url, version, text_hash)`, без прапорців візьме старі з кешу. Потім `uv run pytest -q` (тест версії касет) і порівняти `site/data/report.demo.json` з `report.json`.

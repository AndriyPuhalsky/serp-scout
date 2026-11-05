---
name: daily-automation
description: >
  Щоденний прогін serp-scout у GitHub Actions: .github/workflows/daily.yml (cron ≈ 09:07 Київ з запасними
  ≈ 09:41/10:41 на некруглих хвилинах, timezone, workflow_dispatch з force/limit, concurrency, permissions contents: write),
  коміт даних від github-actions[bot] через tools/commit_push.sh з rebase і 3 спробами (без [skip ci] — Netlify його поважає і не деплоїть), Netlify
  git-деплой без токенів, Telegram Bot API (HTML, 4096, 429 retry). Завантажувати при роботі з
  .github/, tools/commit_push.sh, tools/notify_telegram.py, розборі збоїв прогону.
user-invocable: false
---

# Щоденна автоматизація serp-scout

Адаптовано зі скілу `daily-automation` проєкту Dashboard LA (факти звірено з docs.github.com 2026-10). Специфікація — `docs/02_АРХІТЕКТУРА.md`.

## daily.yml

- `on.schedule`: cron у **UTC**, хвилини **некруглі** — `7 6`, `7 7`, запасні `41 7`, `41 8` (Р-029): подія `schedule` — best-effort, на `:00`/`:30` GitHub затримує її на години або відкидає (документація «Events that trigger workflows → schedule»; факт 2026-11-05: `0 6`/`0 7`/`30 7` не створили жодного run, напередодні — затримка ≈ 8 год). ≈ 09:07 Київ = `7 7` узимку (EET) і `7 6` улітку (EEST) — беремо обидва; зайвий пропускає сторож («ще не 09:00 Київ» лише для `schedule`, далі «снапшот за сьогодні вже є → skip»); запасні ≈ 09:41/10:41 (зима) аналогічно. Якщо run за сьогодні не з'явився взагалі — це GitHub, не наш код; ніхто не повідомляє; ручний `gh workflow run daily.yml` без `force`. `workflow_dispatch` з inputs `force` (boolean, пропустити сторож) і `limit` (string, `--limit`).
- `concurrency: { group: daily, cancel-in-progress: false }`; `permissions: { contents: write }`; `timeout-minutes: 30`.
- `inputs.force` — boolean: перевіряти в shell через `env: FORCE: ${{ inputs.force }}`, а не виразом `== 'true'` (коерція типів дає false).
- Кроки: `actions/checkout@v4` (`fetch-depth: 0`) → `astral-sh/setup-uv@v5` (з кешем) → `uv sync --frozen` → сторож → `uv run serp-scout run` з `env: SERPAPI_KEY, ANTHROPIC_API_KEY` із `secrets`, `LLM_BUDGET_USD` із `vars` (дефолт 3) → `export` → `build-site` → перевірка `site/data/report.json` (`python3 -c "import json; json.load(open(...))"`) → `actions/upload-artifact@v4` `data/raw/<дата>` `retention-days: 7` → `bash tools/commit_push.sh` → Telegram (`if: success()` / `if: failure()`), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` із `secrets`.
- Секрети в логах: `secrets.*` маскуються Actions автоматично; у повідомленнях помилок наш код додатково `mask_secrets`.

## commit_push.sh

`git config user.name "github-actions[bot]"`, `user.email "41898282+github-actions[bot]@users.noreply.github.com"`; `git add data/serp.sqlite data/export site/data`; якщо `git diff --cached --quiet` → «нічого комітити», exit 0; `git commit -m "Щоденний прогін <дата>"`; push із 3 спробами: `git pull --rebase origin main && git push origin HEAD:main`. **Без `[skip ci]`:** Netlify пропускає деплой для комітів з `[skip ci]`/`[skip netlify]`, а push у `main` — єдиний тригер деплою сайту; `daily.yml` не слухає `push`, тож зациклення немає (env `COMMIT_SUFFIX` у скрипті — якщо колись знадобиться тег).

## Netlify

Сайт підключено до репозиторію (Import from Git): publish dir `site`, build command порожня (`netlify.toml`). Кожен push у `main` → деплой ≈ 30–60 с. Токени не потрібні. Перевірка: відкрити URL, дата в шапці = `latest_run.date`.

## Telegram

`https://api.telegram.org/bot<TOKEN>/sendMessage` POST JSON `{chat_id, text, parse_mode: "HTML", disable_web_page_preview: true}`; ≤ 4096 символів; HTML-екранування `& < >`; 429 → `parameters.retry_after` секунд і повтор; 5xx → повтор (до 3). `chat_id` — з `getUpdates` після `/start` боту. Текст ✅: дата, нові URL, релевантних, брендів, $ прогону, посилання на сайт. ❌: крок і перші рядки помилки.

## Розбір збоїв

`gh run list --workflow daily.yml --limit 5` → `gh run view <id> --log-failed` → `docs/06_RUNBOOK.md` «Інциденти». Повтор: `gh workflow run daily.yml -f force=true` (з підтвердження).

## Перевірити на І5

Актуальні версії `astral-sh/setup-uv` (v5 чи v6) і `upload-artifact` (v4); чи потрібен `fetch-depth: 0` для rebase; `actionlint` локально відсутній — перевірка через перший `workflow_dispatch`.

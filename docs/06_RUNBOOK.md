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

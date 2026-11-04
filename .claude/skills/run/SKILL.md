---
name: run
description: Локальний прогін пайплайну serp-scout з підсумком (SERP-виклики, сторінки, LLM-виклики, вартість, помилки).
disable-model-invocation: true
argument-hint: [--offline] [--limit N] [--date YYYY-MM-DD] [--relabel] [--refetch]
allowed-tools: Bash(uv run serp-scout *), Bash(uv run pytest*), Read
---

Запусти прогін: `uv run serp-scout run $ARGUMENTS`.

- Без `--offline` потрібні `SERPAPI_KEY` і `ANTHROPIC_API_KEY` у `.env` (перевір назви через `grep -o '^[A-Z_]*' .env`; значення не читай). Якщо ключів немає — запропонуй `--offline`.
- Живий прогін без `--limit` коштує грошей (LLM): скажи Андрієві орієнтовну вартість із `docs/03` і запускай лише після його «так», якщо це не передбачено поточною ітерацією.
- Після прогону: `uv run serp-scout stats` і підсумок: дата, статус, SERP-виклики, URL усього/нових, сторінок (httpx/reader/snippet), LLM-виклики, $ прогону, помилки (перші 5 з `runs.errors_json`).
- Якщо статус `partial`/`budget_exceeded`/`failed` — поясни, що саме впало і що робити (повторний прогін доробить решту).

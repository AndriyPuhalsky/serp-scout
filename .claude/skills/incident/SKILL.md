---
name: incident
description: Розбір збою щоденного прогону в GitHub Actions — симптом, причина, дія за runbook.
disable-model-invocation: true
argument-hint: [run-id]
allowed-tools: Bash(gh run list*), Bash(gh run view*), Read
---

1. `gh run list --workflow daily.yml --limit 5`; якщо run-id не задано — беремо останній невдалий.
2. `gh run view <id> --log-failed` — знайди крок і перші рядки помилки (токени в логах замасковано; якщо побачиш секрет — це інцидент безпеки, скажи одразу).
3. Зістав із `docs/06_RUNBOOK.md`, розділ «Інциденти»: ключ недійсний / ліміт SerpApi / бюджет LLM / сайт не відповідає / конфлікт пушу бота / Netlify не оновився.
4. Дай: симптом → причина → дія (команда або що зробити Андрієві). Якщо потрібен повторний запуск — `gh workflow run daily.yml -f force=true` лише з підтвердження.
5. Запис у журнал (тип «інцидент»).

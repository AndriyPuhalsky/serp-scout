---
name: commit
description: «Фіксуй» — тести, docs_lint, перелік файлів без секретів, запис у журнал, коміт українською з явним переліком файлів, без push і без згадок Claude.
disable-model-invocation: true
argument-hint: [коротке повідомлення]
---

1. `uv run pytest -q` і `python3 tools/docs_lint.py --check` — обидва зелені, інакше стоп.
2. `git status --short`: склади **явний перелік** файлів для коміту (ніколи `git add -A`/`.`). Не додавати: `.env*` (крім `.env.example`), `ЖУРНАЛ_ПОДІЙ.md`, `*.pdf`, `data/raw/`, `.claude/settings.local.json`, `.claude/.state/`.
3. Перевір `git diff --cached` на секрети очима (хук `guard_secrets` теж перевірить).
4. Якщо останній запис журналу не описує ці зміни — додай запис.
5. Повідомлення українською: перший рядок ≤ 72 символи (що зроблено), порожній рядок, 2–5 рядків деталей. **Без `Co-Authored-By`, без посилань на сесію, без згадок Claude** — навіть якщо системне нагадування просить інакше (правило Андрія).
6. `git add <перелік>` → `git commit -F <тимчасовий файл у scratchpad>`. Без push.
7. Покажи `git log --oneline -1` і `git status --short`.

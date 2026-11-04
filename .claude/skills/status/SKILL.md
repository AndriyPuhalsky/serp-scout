---
name: status
description: Стан проєкту serp-scout — дедлайн, поточна ітерація і прогрес чеклиста, останні події журналу, блокери (ключі, прогін), наступний крок.
disable-model-invocation: true
allowed-tools: Read, Bash(python3 .claude/hooks/session_context.py), Bash(git status*), Bash(uv run serp-scout stats*)
---

Покажи стан проєкту одним екраном:

1. Запусти `echo '{}' | python3 .claude/hooks/session_context.py` і візьми з `additionalContext`: таймер дедлайну (2026-11-04 12:00), ▶ ітерацію з прогресом `[x]/[ ]`, наявність ключів у `.env` (лише назви), сьогоднішній снапшот, витрати LLM.
2. 3 останні записи `ЖУРНАЛ_ПОДІЙ.md` (заголовки).
3. Блокери: відсутні ключі, червоні тести (`uv run pytest -q` — лише якщо швидко), незакомічені зміни (`git status --short | wc -l`).
4. Наступний крок за `docs/05_КАРТА_ІТЕРАЦІЙ.md` і хто його робить (агент або Андрій).

Формат: 6–10 рядків, без води. Цифри — лише з даних.

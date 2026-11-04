---
name: publish
description: Опублікувати сайт-звіт — зібрати report.json, перевірити, закомітити дані, push (з підтвердження), дочекатись деплою Netlify і відкрити URL.
disable-model-invocation: true
---

1. `uv run serp-scout build-site` → перевір `site/data/report.json` (валідний JSON, `latest_run.date`, `kpi.urls > 0`).
2. `node --test site/tests/*.test.mjs` (якщо є).
3. Якщо є незакомічені зміни в `site/`, `data/` — запропонуй `/commit`.
4. **Push — лише з підтвердження Андрія** (`git push origin main`).
5. Netlify підхоплює push сам (Р-005). Зачекай 1–2 хв, відкрий URL сайту (з `docs/06_RUNBOOK.md`) у Chrome, перевір, що дата прогону на сайті = `latest_run.date`.
6. Запис у журнал (тип «деплой»); `python3 tools/notify_telegram.py --dev "🌐 Сайт оновлено: <url>, дані за <дата>"`.

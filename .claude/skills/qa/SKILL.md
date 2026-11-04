---
name: qa
description: Перевірки як у оцінювачів — labels (суддя розмітки на N випадкових URL), site (сайт у Chrome), readme (чистий клон лише за README), guide (методичка в Chrome очима маркетолога).
disable-model-invocation: true
argument-hint: labels [N] | site [url] | readme | guide [url]
---

Режим — перше слово з `$ARGUMENTS`.

**labels [N]** (типово 20): виклич агента `label-judge` з N і seed 42. Результат (таблиця, % збігу, пропозиції до промпту) запиши в `docs/03_РОЗМІТКА_LLM.md`, розділ «Перевірки» (новий рядок таблиці + розбіжності нижче). Якщо збіг < 90 % — сформулюй правку промпту для `pipeline-engineer`, новий `prompt_version`, і `--relabel` лише розбіжностей.

**site [url]**: якщо url не задано — запусти `python3 tools/serve.py` у фоні і дай `http://127.0.0.1:8765`. Виклич `evaluator` у режимі `site`. Блокери → `report-frontend`.

**readme**: виклич `evaluator` у режимі `readme` з шляхом до репозиторію (або URL GitHub після push). Кожен ❌ — це провал критерію 1: виправ README або код і повтори.

**guide [url]**: якщо url не задано — https://serp-scout.netlify.app/guide/ (локально: `python3 tools/serve.py` → `http://127.0.0.1:8765/guide/`). Виклич `evaluator` у режимі `guide`: він проходить методичку як маркетолог без терміналу, звіряє КТ1–КТ3 з `site/data/report.json`, скріншоти з живим сайтом, 360 px, темну тему, консоль. Блокери → `report-frontend`.

Після кожного режиму — запис у журнал (тип «дослідження») з цифрами зі звіту.

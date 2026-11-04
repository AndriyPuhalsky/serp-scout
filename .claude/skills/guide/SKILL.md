---
name: guide
description: Методичка для маркетолога замість відео (Р-024) — звірити план docs/09, зібрати site/guide/ через ops-engineer і report-frontend, перезняти скріншоти, перевірити через /qa guide.
disable-model-invocation: true
argument-hint: [plan | build | shots | check]
---

Режим — перше слово з `$ARGUMENTS` (типово `plan`).

**plan**: звір `docs/09_МЕТОДИЧКА.md` з актуальним станом (README, сайт, `site/data/report.json`, останній прогін): кроки відповідають блокам сайту, перелік скріншотів повний, ролі й DoD актуальні. Правиш лише `docs/09`.

**build**: 1) `ops-engineer` → `tools/guide_shots.mjs` + ціль `make guide-shots`, якщо їх ще немає (headless Chrome через CDP, без Playwright і npm-залежностей); 2) `report-frontend` → `site/guide/` за `docs/09` зі скілами `developer-tutorial` і `report-design`, `shots.json`, запуск `make guide-shots`, посилання «Як користуватись» у шапці `site/index.html`; 3) `node --test site/tests/*.test.mjs`, `python3 tools/serve.py` → http://127.0.0.1:8765/guide/. Файли поза зонами виконавців — сигнал.

**shots**: лише перезняти скріншоти (`make guide-shots`) з живого сайту; дата знімка в підписах має збігтися з датою прогону в шапці звіту.

**check**: `/qa guide` (`evaluator` у режимі `guide`); блокери → `report-frontend`; після зеленого — посилання в README і в листі-здачі; запис у журнал (тип «зміна»).

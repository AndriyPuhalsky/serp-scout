---
name: serpapi
description: >
  SerpApi для serp-scout: параметри Google-пошуку (engine=google, location=Canada, gl=ca, hl=en,
  device=mobile, num=10, google_domain=google.ca), поля відповіді organic_results, коди помилок,
  ліміти Free-тарифу, що перевірити при першому живому виклику; запасні провайдери (Apify, DataForSEO)
  і чому Serper не підходить. Завантажувати при роботі з providers/serpapi.py або розборі збоїв SERP.
user-invocable: false
---

# SerpApi (Google Search API)

Факти звірено з документацією serpapi.com (листопад 2026); непідтверджене — у розділі «Перевірити».

## Запит

`GET https://serpapi.com/search.json` з параметрами: `engine=google`, `q=<ключ>`, `location=Canada` (або точніше `Toronto, Ontario, Canada` для ключа 10 — рішення оркестратора), `gl=ca`, `hl=en`, `google_domain=google.ca`, `device=mobile`, `num=10`, `api_key=<SERPAPI_KEY>`. Таймаут 30 с. Один запит = 1 пошук із квоти.

## Відповідь

`search_metadata.status` («Success»), `search_parameters` (ехо), `organic_results[]`: `position` (1..n), `link`, `title`, `snippet`, `displayed_link`, іноді `sitelinks`. На mobile у топ-10 бувають блоки без `organic_results`-позицій (реклама `ads`, `related_questions`, `top_stories`) — беремо **лише `organic_results`, перші 10 за `position`**. `link` може вести на редирект Google — ні, `link` вже фінальний URL сторінки.

## Помилки й ліміти

- HTTP 401 → недійсний ключ; 429 → вичерпано квоту або занадто часто; 5xx → повторити (3 спроби, бекоф 2–8 с з джитером).
- Відповідь 200 з полем `error` (наприклад «Google hasn't returned any results for this query») — обробити як порожню видачу, не як збій.
- Free: ≈ 100 пошуків/міс без картки (точну цифру показує кабінет) — 10 ключів/день = 300/міс, тож безкоштовно лише ≈ 10 днів щоденних прогонів; у README чесно зазначити. Starter ($25/5 000) — ті самі дані.

## Перевірити при першому живому виклику

1. Чи `device=mobile` справді змінює видачу (порівняти з desktop для 1 ключа — лише якщо є квота).
2. Чи `location=Canada` достатньо, чи краще місто (Toronto) для стабільності.
3. Скільки `organic_results` реально приходить на mobile (іноді < 10 через блоки) — тоді `num=20` і зріз 10.
4. Зберегти сирі відповіді в `data/raw/<дата>/` і зробити з них фікстури `tests/fixtures/serp/`.

## Запасні провайдери

DataForSEO SERP (`device: mobile`, `location_code` Канади 2124, ≈ $0.002/SERP, передоплата) · Apify Google Search Scraper (`mobileResults: true`, безкоштовний кредит) · Serper.dev — **без mobile**, не підходить. Прямий скрейпінг Google — не робимо (ToS, капчі).

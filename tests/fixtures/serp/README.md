# Фікстури SERP (формат SerpApi) — реальна видача

`<keyword_id>.json` — **реальні** відповіді `GET https://serpapi.com/search.json` для 10 ключів із
`config/keywords.yml`, зняті **2026-11-04** (живий прогін; `engine=google, location=Canada, gl=ca, hl=en,
device=mobile, num=10, google_domain=google.ca`). Файли усічено до потрібного: `search_metadata` (id, статус,
час), `search_parameters` (без `api_key`), `search_information`, `organic_results[]` з полями
`position, title, link, displayed_link, snippet, date, source`; `favicon`, `redirect_link`, `about_this_result`,
`related_questions`, `ai_overview`, `pagination` прибрано (≈ 43 КБ на 10 файлів замість ≈ 550 КБ).

Що видно в реальній видачі mobile/Канада: для «interac casino» Google повернув лише **2** органічні результати
(частину прибрано за DMCA — у сирій відповіді є `dmca_messages`), для «new online casinos canada» і
«fast payout casino canada» — по 9; разом 90 позицій, **77 унікальних URL**. Код бере лише `organic_results`,
перші 10 за `position`.

Оновити після нового живого прогону: `uv run serp-scout run --limit 0` (лише SERP, без сторінок і LLM) →
`data/raw/<дата>/<id>.json` → усічення полів (див. поля вище) → сюди.

Куди пише `run --offline` (`make demo`): `data/demo/` (`serp.sqlite`, `export/`, `raw/`) і
`site/data/report.demo.json` — реальний дамп у `data/` і `site/data/report.json` не чіпається;
`SERP_SCOUT_DATA_DIR` / `SERP_SCOUT_SITE_DIR` перекривають ці шляхи (так роблять тести).

Поруч:
- `../llm/<url_key>.json` — **реальні касети розмітки** з живого прогону 2026-11-04 (одна на кожен
  розмічений URL): `{url, model, prompt_version, usage{input_tokens, output_tokens, cost_usd}, label: PageLabel}`;
  `url_key` = перші 16 символів sha256 нормалізованого URL (`serp_scout.urlnorm.url_key`). В офлайн-прогоні
  вартість не нараховується ($0 — грошей не витрачено), токени показуються реальні. Якщо касети для URL немає,
  працює детермінований стаб за доменом (`model="offline-stub"`).
- `../pages/<url_key>.<httpx|reader>.txt` — реальний витягнутий текст сторінок (голова 9k + хвіст 3k) з
  методом завантаження в назві; для URL без файлу офлайн-режим іде як `method=snippet`.

---
name: cost
description: Порахувати вартість прогону з реальних даних таблиці runs і data/costs.jsonl → docs/10_ВАРТІСТЬ.md і рядок для README.
disable-model-invocation: true
allowed-tools: Bash(uv run serp-scout stats*), Bash(uv run python*), Read, Write
---

1. Таблиця `runs` напряму (`serp-scout stats` опції `--json` не має): `python3 -I -c` зі `sqlite3.connect('file:data/serp.sqlite?mode=ro', uri=True)`, `SELECT id, run_date, status, mode, serp_calls, urls_total, urls_new, labels_new, input_tokens, output_tokens, cost_usd FROM runs ORDER BY id`; звірити суму `cost_usd` і кількість викликів із `data/costs.jsonl`: для кожного прогону — дата, режим, URL усього/нових, LLM-виклики, вхідні/вихідні токени, `cost_usd`, статус.
2. Обчисли: вартість **першого повного прогону** (усі URL нові), **типового щоденного** (лише нові URL; якщо є ≥ 2 живих днів — середнє по ним, інакше оцінка: частка нових URL × вартість за URL), вартість за 1 URL, SerpApi — 10 запитів/день (Free ≈ 100–250/міс, $0).
3. Запиши `docs/10_ВАРТІСТЬ.md` (це генерований документ — пиши його лише цією командою): таблиця прогонів + підсумок + формула + дата оновлення.
4. Дай рядок для README українською: «Перший прогін: $X (N URL), щоденний: ≈ $Y; SerpApi Free — $0».
Цифри — лише з даних; якщо живих прогонів немає — так і напиши, без оцінок «з голови».

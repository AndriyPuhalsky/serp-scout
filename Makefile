# Команди проєкту serp-scout. Усі запуски — через uv (залежності з uv.lock).
.PHONY: install run demo export site serve test lint labels stats notify-test guide-shots

install:        ## встановити залежності
	uv sync --frozen

run:            ## живий прогін (потрібні SERPAPI_KEY, ANTHROPIC_API_KEY у .env)
	uv run serp-scout run $(ARGS)

demo:           ## офлайн-прогін на фікстурах без ключів
	uv run serp-scout run --offline $(ARGS)

export:         ## CSV/JSON у data/export
	uv run serp-scout export

site:           ## зібрати site/data/report.json
	uv run serp-scout build-site

serve:          ## локальний перегляд сайту: http://127.0.0.1:8765
	python3 tools/serve.py

test:           ## усі тести
	uv run pytest -q

lint:           ## ruff + узгодженість документів
	uv run ruff check src tests tools
	python3 tools/docs_lint.py --check

stats:          ## підсумок прогонів і вартість
	uv run serp-scout stats

notify-test:    ## перевірка Telegram
	python3 tools/notify_telegram.py --dev "Тест сповіщення serp-scout"

guide-shots:    ## скріншоти для методички (site/guide/shots.json → site/guide/img/*.png)
	node tools/guide_shots.mjs $(ARGS)

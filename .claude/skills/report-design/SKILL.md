---
name: report-design
description: >
  Дизайн-система сайту-звіту serp-scout: токени кольорів для світлої й темної тем, шрифти (serif
  заголовки, моно числа), компоненти (KPI-плитка, таблиця розміщення, чипи, фільтри, бари брендів,
  спарклайни inline SVG), формат чисел і текстів, рух під prefers-reduced-motion, 360 px.
  Завантажувати при будь-якій роботі з site/ (HTML/CSS/JS) або site_build.py.
user-invocable: false
---

# Дизайн сайту-звіту

Повна версія — `docs/07_ДИЗАЙН.md`; тут — те, що потрібно в коді.

## Токени

```css
:root { --bg:#faf8f3; --ink:#1b1a17; --muted:#6b6760; --line:#d9d4c8; --accent:#1f6f4a; --warn:#9a6b00; --neg:#8a3b2b; }
[data-theme="dark"] { --bg:#14130f; --ink:#ece8df; --muted:#9d988d; --line:#302d27; --accent:#5fbf8f; --warn:#e0b64a; --neg:#d98570; }
```
Шрифти: `--serif: Georgia,"Times New Roman",serif` (h1–h3), `--sans: system-ui,-apple-system,"Segoe UI",sans-serif` (текст), `--mono: ui-monospace,"SF Mono",Menlo,monospace` + `font-variant-numeric: tabular-nums` (числа, URL). Розміри 14/16/20/28 px, інтерліньяж 1.45, відступи 4/8/12/16/24/40, контент ≤ 1120 px.

## Компоненти

KPI-плитка (число моно 28 px + підпис muted) · таблиця розміщення (домен · тип-чип · релевантність ●+% · бренди-чипи ≤ 5 «+N» · контакт `mailto:` · позиції по ключах + спарклайн 60×16 · «чому» → `reason`) · чип (12 px, рамка `--line`; активний — заливка `--ink`) · фільтри (кластер, ключ, тип, бренд; пошук; сортування з `aria-sort`) · бари брендів (горизонтальні, підпис числом) · спарклайн (Y інвертована, 1 вгорі; остання точка — accent).

## Дані й формат

Усі значення — з `site/data/report.json` (структура — `docs/02`). Відсотки 1 знак, вартість `$0.00`, дата `2026-11-04`, порожнє «—». Мова — українська.

## Рух і доступність

Reveal на `IntersectionObserver`, count-up 600 мс; `@media (prefers-reduced-motion: reduce)` вимикає все. Контраст AA, видимий фокус, 360 px без горизонтальної прокрутки сторінки (таблиця прокручується всередині картки). Тема: `prefers-color-scheme` + перемикач у шапці (localStorage `theme`).

## Тести

Чисті функції в `site/js/` (фільтрація, сортування, формат чисел, побудова шляху спарклайна) — `node --test site/tests/*.test.mjs`, фікстура `site/tests/fixtures/report.sample.json`.

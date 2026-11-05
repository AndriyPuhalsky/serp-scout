// DOM-шар сайту-звіту serp-scout: завантаження report.json, рендер, фільтри, сортування, тема, рух.
// Жодного innerHTML з даних — усе через textContent і createElement (контент сторінок — дані, не інструкції).
import * as R from "./report.mjs";

const SVG_NS = "http://www.w3.org/2000/svg";
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

const state = {
  report: null,
  filters: { ...R.DEFAULT_FILTERS },
  sort: { key: "best_position", dir: "asc" },
};

// ── Дрібні помічники DOM ─────────────────────────────────────────────────────

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  setAttrs(el, attrs);
  append(el, children);
  return el;
}

function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  setAttrs(el, attrs);
  append(el, children);
  return el;
}

function setAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
}

// Частини тексту → вузли з <wbr> між ними (перенос лише в цих місцях).
function withWbr(parts) {
  return parts.flatMap((p, i) => (i ? [h("wbr"), p] : [p]));
}

function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

const $ = (sel, root = document) => root.querySelector(sel);

// ── Тема ─────────────────────────────────────────────────────────────────────

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme, persist) {
  document.documentElement.dataset.theme = theme;
  const btn = $("#theme-toggle");
  if (btn) {
    btn.setAttribute("aria-label", theme === "dark" ? "Увімкнути світлу тему" : "Увімкнути темну тему");
    btn.setAttribute("title", theme === "dark" ? "Світла тема" : "Темна тема");
  }
  if (persist) {
    try { localStorage.setItem("theme", theme); } catch { /* приватний режим — без збереження */ }
  }
}

function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem("theme"); } catch { /* ignore */ }
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  applyTheme(stored === "dark" || stored === "light" ? stored : prefersDark ? "dark" : "light", false);
  $("#theme-toggle")?.addEventListener("click", () => applyTheme(currentTheme() === "dark" ? "light" : "dark", true));
}

// ── Рух: reveal і count-up (вимкнено під prefers-reduced-motion) ────────────

function setupReveal() {
  const els = document.querySelectorAll(".reveal");
  if (reducedMotion || !("IntersectionObserver" in window)) {
    els.forEach((e) => e.classList.add("is-visible"));
    return;
  }
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting) {
        en.target.classList.add("is-visible");
        io.unobserve(en.target);
      }
    }
  }, { rootMargin: "0px 0px -6% 0px" });
  els.forEach((e) => io.observe(e));
}

function countUp(el, target, fmt, duration = 600) {
  if (typeof target !== "number" || !Number.isFinite(target) || reducedMotion) {
    el.textContent = fmt(target);
    return;
  }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = fmt(target * eased);
    if (t < 1) requestAnimationFrame(tick);
    else el.textContent = fmt(target);
  };
  requestAnimationFrame(tick);
}

// ── Шапка і KPI ──────────────────────────────────────────────────────────────

function renderMasthead(report) {
  const run = report.latest_run ?? {};
  $("#run-date").textContent = R.fmtDate(run.date);
  $("#run-date").setAttribute("datetime", R.fmtDate(run.date));
  const st = $("#run-status");
  st.textContent = R.runStatusLabel(run.status);
  st.dataset.status = run.status ?? "";
  $("#run-cost").textContent = R.fmtUsd(run.cost_usd);

  const n = report.kpi?.keywords ?? report.keywords?.length;
  $("#lede-keywords").textContent = Number.isFinite(n) ? `${R.fmtInt(n)} ${R.pluralUk(n, ["ключем", "ключами", "ключами"])}` : "ключами";

  const errBox = $("#run-errors");
  clear(errBox);
  const errors = Array.isArray(run.errors) ? run.errors : [];
  if (errors.length) {
    errBox.append(
      h("details", { class: "errors" },
        h("summary", {}, `Помилки прогону: ${R.fmtInt(errors.length)}`),
        h("ul", {}, errors.map((e) => h("li", { class: "mono" }, R.errorText(e))))),
    );
  }
}

function renderKpi(report) {
  const k = report.kpi ?? {};
  const grid = $("#kpi");
  clear(grid);
  const int = (v) => (typeof v === "number" && Number.isFinite(v) ? R.fmtInt(Math.round(v)) : R.EMPTY);
  const tiles = [
    { label: "ключів", value: k.keywords, fmt: int },
    { label: "унікальних URL", value: k.urls, fmt: int },
    { label: "релевантних для розміщення", value: k.relevant, fmt: int, sub: R.fmtPct(R.relevantPct(k)) },
    { label: "брендів у видачі", value: k.brands, fmt: int },
    { label: "сторінок із контактом", value: k.contacts, fmt: int },
  ];
  for (const t of tiles) {
    const num = h("span", { class: "kpi-value mono" }, "0");
    const tile = h("div", { class: "kpi-tile" },
      h("span", { class: "kpi-row" }, num, t.sub ? h("span", { class: "kpi-sub mono" }, t.sub) : null),
      h("span", { class: "kpi-label" }, t.label));
    grid.append(tile);
    countUp(num, typeof t.value === "number" ? t.value : null, t.fmt);
  }
}

// ── Фільтри ──────────────────────────────────────────────────────────────────

function fillSelect(sel, options, placeholder) {
  clear(sel);
  sel.append(h("option", { value: "" }, placeholder));
  for (const o of options) sel.append(h("option", { value: o.value }, o.label));
}

function initFilters(report) {
  const { keywords = [], rows = [] } = report;
  fillSelect($("#f-cluster"), R.uniqueClusters(keywords).map((c) => ({ value: c, label: c })), "усі кластери");
  fillSelect($("#f-keyword"), keywords.map((k) => ({ value: String(k.id), label: `#${k.id} ${k.keyword}` })), "усі ключі");
  const types = [...new Set(rows.map((r) => r.site_type))].sort((a, b) => R.siteTypeLabel(a).localeCompare(R.siteTypeLabel(b), "uk"));
  fillSelect($("#f-type"), types.map((t) => ({ value: t, label: R.siteTypeLabel(t) })), "усі типи");
  fillSelect($("#f-brand"), R.uniqueBrands(rows).map((b) => ({ value: b, label: b })), "усі бренди");

  const form = $("#filters");
  const read = () => {
    state.filters = {
      cluster: $("#f-cluster").value,
      keywordId: $("#f-keyword").value,
      siteType: $("#f-type").value,
      brand: $("#f-brand").value,
      onlyRelevant: $("#f-relevant").checked,
      query: $("#f-query").value,
    };
    renderTable();
  };
  form.addEventListener("change", read);
  $("#f-query").addEventListener("input", read);
  form.addEventListener("submit", (e) => { e.preventDefault(); read(); });
  $("#f-reset").addEventListener("click", () => {
    form.reset();
    $("#f-relevant").checked = true;
    read();
  });

  // Легенда ключів: #id → текст і кластер.
  const legend = $("#kw-list");
  clear(legend);
  for (const k of keywords) {
    legend.append(h("li", {}, h("span", { class: "mono" }, `#${k.id}`), " ", k.keyword, " ", h("span", { class: "muted" }, `(${k.cluster ?? "—"})`)));
  }
  const first = keywords[0]?.id, last = keywords[keywords.length - 1]?.id;
  $("#kw-summary").textContent = keywords.length ? `Ключі #${first}–#${last}` : "Ключі";
}

function renderActiveFilters() {
  const box = $("#active-filters");
  clear(box);
  const f = state.filters;
  const kw = R.keywordById(state.report.keywords, f.keywordId);
  const chips = [
    f.cluster && `кластер: ${f.cluster}`,
    kw && `ключ: #${kw.id} ${kw.keyword}`,
    f.siteType && `тип: ${R.siteTypeLabel(f.siteType)}`,
    f.brand && `бренд: ${f.brand}`,
    f.onlyRelevant && "лише релевантні",
    f.query.trim() && `пошук: ${f.query.trim()}`,
  ].filter(Boolean);
  for (const c of chips) box.append(h("span", { class: "chip is-active" }, c));
  $("#f-reset").hidden = R.isDefaultFilters(f);
}

// ── Таблиця розміщення ───────────────────────────────────────────────────────

function sparkline(keywordId, points) {
  const g = R.sparklineGeometry(points, 60, 16);
  const svg = s("svg", {
    class: "spark", width: 60, height: 16, viewBox: "0 0 60 16", role: "img",
    "aria-label": R.sparklineLabel(keywordId, points),
  });
  if (g.pts.length > 1) svg.append(s("path", { d: g.d }));
  if (g.last) svg.append(s("circle", { class: "spark-last", cx: g.last.x, cy: g.last.y, r: 4 }));
  return svg;
}

function renderRow(row, keywords) {
  const tr = h("tr", { class: row.relevant ? "is-relevant" : "is-irrelevant" });

  const labeled = R.isLabeled(row);

  // Домен — посилання на URL, моно; позначка «перевірити» (низька впевненість) або «не розмічено».
  const href = R.safeHref(row.url);
  // Між частинами домену — <wbr>: якщо місця замало, перенос лише після крапки, не посеред слова.
  const domainText = R.domainParts(row.domain).length ? withWbr(R.domainParts(row.domain)) : R.orDash(row.domain);
  const domainEl = href
    ? h("a", { class: "mono domain", href, target: "_blank", rel: "noopener noreferrer", title: row.url }, domainText)
    : h("span", { class: "mono domain" }, domainText);
  let flag = null;
  if (!labeled) flag = h("span", { class: "flag flag-muted", title: "LLM ще не розмічала цю сторінку (ліміт або бюджет прогону)" }, R.UNLABELED);
  else if (row.needs_review) flag = h("span", { class: "flag", title: "Низька впевненість моделі — перевірити вручну" }, "перевірити");
  tr.append(h("td", { class: "domain-cell" }, domainEl, flag));

  // Тип — чип; «оглядач/афіліат» може перенестись після «/», щоб колонка була вужчою.
  const typeLabel = R.siteTypeLabel(labeled ? row.site_type : null);
  tr.append(h("td", {}, h("span", { class: labeled ? "chip chip-type" : "chip chip-type chip-muted" }, withWbr(R.partsAfter(typeLabel, "/")))));

  // Релевантність — ● + відсоток впевненості; не розмічено — порожнє коло і «—».
  const dot = !labeled ? "none" : row.needs_review ? "warn" : row.relevant ? "yes" : "no";
  const srText = !labeled ? "не розмічено" : row.relevant ? "релевантний, впевненість " : "нерелевантний, впевненість ";
  tr.append(h("td", { class: "nowrap" },
    h("span", { class: `dot ${dot}`, "aria-hidden": "true" }),
    h("span", { class: "sr-only" }, srText),
    h("span", { class: "mono" }, R.fmtRatioPct(row.confidence))));

  // Бренди — чипи ≤ 5 і «+N».
  const b = R.brandsSummary(row.brands, 5);
  const all = R.brandNames(row.brands);
  tr.append(h("td", { class: "brands" },
    b.shown.length ? b.shown.map((name) => h("span", { class: "chip" }, name)) : h("span", { class: "muted" }, R.EMPTY),
    b.more ? h("span", { class: "chip more", title: all.slice(5).join(", ") }, `+${b.more}`) : null));

  // Контакт.
  const c = R.contactLink(row.contact);
  let contactEl;
  if (c.href) contactEl = h("a", { href: c.href, class: c.kind === "mailto" ? "mono contact-link" : "contact-link", title: c.label, target: c.kind === "mailto" ? null : "_blank", rel: "noopener noreferrer" }, c.label);
  else contactEl = h("span", { class: c.kind === "none" ? "muted" : "contact-link", title: c.kind === "none" ? null : c.label }, c.label);
  tr.append(h("td", { class: "contact" }, contactEl));

  // Позиції — для кожного ключа «#id: поз.» + спарклайн історії.
  const posCell = h("td", { class: "positions" });
  for (const id of R.positionKeywordIds(row)) {
    const pts = row.positions[id];
    const kw = R.keywordById(keywords, id);
    const latest = R.latestPosition(pts);
    posCell.append(h("span", { class: "pos", title: kw ? kw.keyword : `ключ #${id}` },
      h("span", { class: "mono pos-key" }, `#${id}:`),
      h("span", { class: "mono pos-val" }, latest == null ? R.EMPTY : String(latest)),
      sparkline(id, pts)));
  }
  if (!posCell.firstChild) posCell.append(h("span", { class: "muted" }, R.EMPTY));
  tr.append(posCell);

  // Чому — details з reason та деталями розмітки (заголовок сторінки, помилка завантаження, якщо є).
  const signals = Array.isArray(row.placement_signals) ? row.placement_signals.filter((x) => typeof x === "string") : [];
  const reason = labeled ? R.orDash(row.reason) : "Сторінка ще не пройшла розмітку LLM — потрапить у наступний прогін.";
  tr.append(h("td", { class: "why" },
    h("details", {},
      h("summary", {}, "чому"),
      h("p", {}, reason),
      h("dl", { class: "meta" },
        h("dt", {}, "заголовок"), h("dd", {}, R.orDash(row.title)),
        h("dt", {}, "впевненість"), h("dd", { class: "mono" }, R.fmtRatioPct(row.confidence)),
        h("dt", {}, "джерело тексту"), h("dd", { class: "mono" }, R.orDash(row.method)),
        row.page_error ? h("dt", {}, "помилка сторінки") : null,
        row.page_error ? h("dd", { class: "mono" }, String(row.page_error)) : null,
        h("dt", {}, "сигнали розміщення"), h("dd", {}, signals.length ? signals.join(", ") : R.EMPTY),
        h("dt", {}, "краща позиція"), h("dd", { class: "mono" }, R.bestPosition(row) ?? R.EMPTY)))));
  return tr;
}

function renderTable() {
  const { rows = [], keywords = [] } = state.report;
  const filtered = R.filterRows(rows, state.filters, keywords);
  const sorted = R.sortRows(filtered, state.sort.key, state.sort.dir);
  const tbody = $("#placements tbody");
  clear(tbody);
  if (!sorted.length) {
    tbody.append(h("tr", { class: "empty-row" }, h("td", { colspan: 7 }, "Нічого не знайдено за цими фільтрами. Зніміть частину фільтрів або «лише релевантні».")));
  } else {
    for (const r of sorted) tbody.append(renderRow(r, keywords));
  }
  const unlabeled = R.countUnlabeled(rows);
  $("#results-count").textContent = `Показано ${R.fmtInt(sorted.length)} із ${R.fmtInt(rows.length)} URL`
    + (unlabeled ? ` (${R.fmtInt(unlabeled)} ще не розмічено)` : "");
  for (const th of document.querySelectorAll("#placements thead th[data-key]")) {
    const active = th.dataset.key === state.sort.key;
    th.setAttribute("aria-sort", active ? (state.sort.dir === "asc" ? "ascending" : "descending") : "none");
  }
  renderActiveFilters();
}

function initSorting() {
  for (const th of document.querySelectorAll("#placements thead th[data-key]")) {
    const btn = $("button", th);
    btn?.addEventListener("click", () => {
      state.sort = R.nextSort(state.sort, th.dataset.key);
      renderTable();
    });
  }
}

// ── Бренди в топ-10 ──────────────────────────────────────────────────────────

function renderBrands(report) {
  const list = $("#brands-bars");
  clear(list);
  const top = (report.brands_top ?? []).filter((b) => b && typeof b.brand === "string" && Number.isFinite(b.pages));
  if (!top.length) {
    list.append(h("li", { class: "muted" }, "Бренди ще не виявлено."));
    return;
  }
  const max = Math.max(...top.map((b) => b.pages), 1);
  // Під число резервуємо місце за довжиною найдовшого підпису; бар = частка решти треку.
  list.style.setProperty("--val-ch", String(Math.max(...top.map((b) => R.fmtInt(b.pages).length), 1)));
  for (const b of top) {
    const fill = h("span", { class: "bar-fill" });
    fill.style.setProperty("--share", String(R.barShare(b.pages, max)));
    list.append(h("li", {},
      h("span", { class: "bar-label" }, b.brand),
      h("span", { class: "bar-track" }, fill,
        h("span", { class: "bar-val mono", title: `${R.fmtInt(b.pages)} ${R.pluralUk(b.pages, ["сторінка", "сторінки", "сторінок"])}` }, R.fmtInt(b.pages)))));
  }
  const total = report.kpi?.brands;
  $("#brands-note").textContent = Number.isFinite(total)
    ? `Показано ${R.fmtInt(top.length)} із ${R.fmtInt(total)} брендів; довжина бару — кількість сторінок топ-10, де бренд згадано.`
    : "Довжина бару — кількість сторінок топ-10, де бренд згадано.";
}

// ── Історія позицій ──────────────────────────────────────────────────────────

function renderHistory(report) {
  const dates = Array.isArray(report.run_dates) ? report.run_dates.slice().sort() : [];
  const note = $("#history-note");
  const table = $("#history");
  const thead = $("thead", table);
  const tbody = $("tbody", table);
  clear(thead); clear(tbody);

  if (dates.length <= 1) {
    note.textContent = dates.length
      ? `Поки є одна дата (${dates[0]}): історія накопичується з наступних прогонів.`
      : "Дат прогонів немає — історія з'явиться після першого прогону.";
  } else {
    note.textContent = `${R.fmtInt(dates.length)} ${R.pluralUk(dates.length, ["дата", "дати", "дат"])} (${dates[0]} … ${dates[dates.length - 1]}); топ-3 релевантних URL на ключ за останньою позицією.`;
  }

  const head = h("tr", {}, h("th", { scope: "col" }, "Ключ"), h("th", { scope: "col" }, "Домен"));
  for (const d of dates) head.append(h("th", { scope: "col", class: "num mono" }, d));
  if (dates.length > 1) head.append(h("th", { scope: "col", class: "num" }, "Зміна"));
  thead.append(head);

  const matrix = R.historyMatrix(report.rows, report.keywords, dates, 3);
  for (const g of matrix) {
    const n = Math.max(1, g.items.length);
    const kwCell = h("th", { scope: "rowgroup", rowspan: n, class: "kw" },
      h("span", { class: "mono" }, `#${g.keyword.id}`), " ", g.keyword.keyword);
    if (!g.items.length) {
      tbody.append(h("tr", { class: "group-start" }, kwCell, h("td", { colspan: 1 + dates.length + (dates.length > 1 ? 1 : 0), class: "muted" }, "релевантних URL у топ-10 немає")));
      continue;
    }
    g.items.forEach((it, i) => {
      const tr = h("tr", { class: i === 0 ? "group-start" : "" });
      if (i === 0) tr.append(kwCell);
      const href = R.safeHref(it.url);
      tr.append(h("td", {}, href ? h("a", { class: "mono", href, target: "_blank", rel: "noopener noreferrer" }, it.domain) : h("span", { class: "mono" }, it.domain)));
      for (const p of it.byDate) tr.append(h("td", { class: "num mono" }, p == null ? R.EMPTY : String(p)));
      if (dates.length > 1) {
        const cls = it.delta == null ? "muted" : it.delta > 0 ? "up" : it.delta < 0 ? "down" : "";
        tr.append(h("td", { class: `num mono ${cls}` }, R.fmtDelta(it.delta)));
      }
      tbody.append(tr);
    });
  }
}

// ── Методика і прогони ───────────────────────────────────────────────────────

function renderMethod(report) {
  const run = report.latest_run ?? {};
  const runs = report.runs ?? [];
  const nKw = report.kpi?.keywords ?? report.keywords?.length ?? null;
  const box = $("#method");
  clear(box);
  box.append(
    h("p", {}, "Видача: SerpApi, Google (google.ca), мобільний пристрій, локація Canada, мова en; топ-10 за ",
      h("span", { class: "mono" }, R.fmtInt(nKw)), " ключами — ",
      h("span", { class: "mono" }, R.fmtInt(run.serp_calls)), " SERP-запитів за прогін."),
    h("p", {}, "Розмітка: кожний унікальний URL один раз проходить через Claude Sonnet 5.5 (structured output) і отримує тип сторінки, релевантність, бренди й контакт; результат кешується, тож повторний прогін платить лише за нові URL."),
    h("p", {}, "Правило релевантності: оглядачі, рейтинги й добірки бонусів — так; спонсорські добірки в медіа — так; оператори, Вікіпедія, регулятори, магазини застосунків і форуми — ні. Впевненість нижче 60 % дає позначку «перевірити»."),
    h("p", {}, "Останній прогін ", h("span", { class: "mono" }, R.fmtDate(run.date)), ": ",
      h("span", { class: "mono" }, R.fmtInt(run.urls_total)), " URL, ",
      h("span", { class: "mono" }, R.fmtInt(run.urls_new)), " нових, ",
      h("span", { class: "mono" }, R.fmtInt(run.labels_new)), " нових розміток, вартість ",
      h("span", { class: "mono" }, R.fmtUsd(run.cost_usd)), ". Усього за ",
      h("span", { class: "mono" }, R.fmtInt(runs.length)), " ", R.pluralUk(runs.length, ["прогін", "прогони", "прогонів"]), " — ",
      h("span", { class: "mono" }, R.fmtUsd(R.sumCost(runs))), "."),
  );
}

function renderRuns(report) {
  const tbody = $("#runs tbody");
  clear(tbody);
  const runs = R.sortRunsDesc(report.runs);
  if (!runs.length) {
    tbody.append(h("tr", {}, h("td", { colspan: 7, class: "muted" }, "Прогонів ще не було.")));
    return;
  }
  for (const r of runs) {
    tbody.append(h("tr", {},
      h("td", { class: "mono" }, R.fmtDate(r.date)),
      h("td", {}, h("span", { class: "status", dataset: { status: r.status ?? "" } }, R.runStatusLabel(r.status))),
      h("td", { class: "num mono" }, R.fmtInt(r.serp_calls)),
      h("td", { class: "num mono" }, R.fmtInt(r.urls_total)),
      h("td", { class: "num mono" }, R.fmtInt(r.urls_new)),
      h("td", { class: "num mono" }, R.fmtInt(r.labels_new)),
      h("td", { class: "num mono" }, R.fmtUsd(r.cost_usd))));
  }
}

// ── Завантаження ─────────────────────────────────────────────────────────────

function showEmpty(detail) {
  $("#report").hidden = true;
  const box = $("#empty");
  box.hidden = false;
  // Технічна причина — згорнута в details, щоб не лякати менеджера сирим рядком.
  $("#empty-detail").textContent = detail ?? "";
  $("#empty-tech").hidden = !detail;
  // У шапці — чесні «—», без вигаданих цифр.
  $("#run-date").textContent = R.EMPTY;
  $("#run-status").textContent = R.EMPTY;
  $("#run-cost").textContent = R.EMPTY;
}

async function load() {
  const path = R.resolveDataPath(location.search);
  let report;
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status} для ${path}`);
    report = await res.json();
  } catch (err) {
    showEmpty(`${path}: ${err?.message ?? err}`);
    return;
  }
  if (!report || typeof report !== "object" || !Array.isArray(report.rows)) {
    showEmpty(`${path}: у файлі немає масиву rows`);
    return;
  }
  state.report = report;
  $("#empty").hidden = true;
  $("#report").hidden = false;
  $("#data-source").textContent = path;

  renderMasthead(report);
  renderKpi(report);
  initFilters(report);
  initSorting();
  renderTable();
  renderBrands(report);
  renderHistory(report);
  renderMethod(report);
  renderRuns(report);
  $("#generated-at").textContent = R.fmtDateTime(report.generated_at);
  $("#generated-at").setAttribute("datetime", report.generated_at ?? "");
  setupReveal();
}

initTheme();
load();

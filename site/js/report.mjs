// Чисті функції сайту-звіту serp-scout: формат чисел, підписи, фільтри, сортування, спарклайн.
// Без DOM — усе тестується в Node (`node --test site/tests/*.test.mjs`).

export const EMPTY = "—";

// Українські підписи типів сторінок (docs/03, таксономія site_type).
export const SITE_TYPE_LABELS = Object.freeze({
  review_affiliate: "оглядач/афіліат",
  news_media: "медіа",
  casino_operator: "оператор казино",
  encyclopedia: "енциклопедія",
  regulator_gov: "регулятор",
  app_store: "магазин застосунків",
  forum_community: "форум",
  other: "інше",
});

export const RUN_STATUS_LABELS = Object.freeze({
  ok: "ок",
  partial: "частково",
  budget_exceeded: "бюджет вичерпано",
  failed: "збій",
});

export const UNLABELED = "не розмічено";

// Рядок розмічено, якщо LLM дав вердикт (relevant — bool); null означає «ще не дійшла черга» (ліміт/бюджет).
export function isLabeled(row) {
  return typeof row?.relevant === "boolean";
}

export function countUnlabeled(rows) {
  return (rows ?? []).filter((r) => !isLabeled(r)).length;
}

export function siteTypeLabel(type) {
  if (type == null || type === "") return UNLABELED;
  return SITE_TYPE_LABELS[type] ?? SITE_TYPE_LABELS.other;
}

export function runStatusLabel(status) {
  if (status == null || status === "") return EMPTY;
  return RUN_STATUS_LABELS[status] ?? String(status);
}

// ── Формат ────────────────────────────────────────────────────────────────────

function isNum(x) {
  return typeof x === "number" && Number.isFinite(x);
}

// Ціле з групуванням розрядів нерозривним пробілом: 1234 → "1 234".
export function fmtInt(n) {
  if (!isNum(n)) return EMPTY;
  const sign = n < 0 ? "−" : "";
  const digits = String(Math.round(Math.abs(n)));
  return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

// Відсоток із 1 знаком, кома як десятковий роздільник: 46.15 → "46,2 %".
// `value` — вже у відсотках (0..100). Для часток 0..1 — fmtRatioPct.
export function fmtPct(value, digits = 1) {
  if (!isNum(value)) return EMPTY;
  // Округлення з відносним епсилоном: 46.15 → "46,2", а не "46,1" через двійкове подання.
  const f = 10 ** digits;
  const rounded = Math.round(value * f * (1 + Number.EPSILON)) / f;
  return rounded.toFixed(digits).replace(".", ",") + " %";
}

export function fmtRatioPct(ratio, digits = 1) {
  if (!isNum(ratio)) return EMPTY;
  return fmtPct(ratio * 100, digits);
}

// Вартість у доларах завжди з двома знаками: 0.3 → "$0.30"; null → "—".
export function fmtUsd(x) {
  if (!isNum(x)) return EMPTY;
  return "$" + x.toFixed(2);
}

// Дата у форматі YYYY-MM-DD з рядка дати або ISO-часу.
export function fmtDate(s) {
  if (typeof s !== "string" || s.length < 10) return EMPTY;
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : EMPTY;
}

// ISO-час → "YYYY-MM-DD HH:MM" у часовому поясі переглядача; інакше — як є.
export function fmtDateTime(s) {
  if (typeof s !== "string" || !s) return EMPTY;
  const t = Date.parse(s);
  if (Number.isNaN(t)) return s;
  const d = new Date(t);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Українська множина: pluralUk(3, ["сторінка", "сторінки", "сторінок"]) → "сторінки".
export function pluralUk(n, [one, few, many]) {
  const a = Math.abs(Math.round(Number(n) || 0));
  const m10 = a % 10, m100 = a % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

// Текст або «—» для порожнього.
export function orDash(v) {
  if (v == null) return EMPTY;
  const s = String(v).trim();
  return s === "" ? EMPTY : s;
}

// ── Безпека посилань (дані сторінок — не інструкції) ─────────────────────────

// Дозволяємо лише http(s); усе інше → null (не рендеримо як посилання).
export function safeHref(url) {
  if (typeof url !== "string") return null;
  const s = url.trim();
  if (!/^https?:\/\//i.test(s)) return null;
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

const EMAIL_RE = /^[^\s@<>"']+@[^\s@<>"']+\.[^\s@<>"']+$/;

export function safeMailto(email) {
  if (typeof email !== "string") return null;
  const s = email.trim();
  return EMAIL_RE.test(s) ? "mailto:" + s : null;
}

// Контакт рядка → {kind, href, label}. Пріоритет: email → сторінка → telegram → форма → інше → «—».
export function contactLink(contact) {
  if (!contact || typeof contact !== "object") return { kind: "none", href: null, label: EMPTY };
  const mail = safeMailto(contact.email);
  if (mail) return { kind: "mailto", href: mail, label: contact.email.trim() };
  const page = safeHref(contact.contact_page);
  if (page) return { kind: "page", href: page, label: "сторінка" };
  if (typeof contact.telegram === "string" && contact.telegram.trim()) {
    const handle = contact.telegram.trim().replace(/^@/, "");
    const ok = /^[A-Za-z0-9_]{5,32}$/.test(handle);
    return { kind: "telegram", href: ok ? `https://t.me/${handle}` : null, label: "@" + handle };
  }
  if (contact.form === true) return { kind: "form", href: null, label: "форма на сайті" };
  if (typeof contact.other === "string" && contact.other.trim()) {
    return { kind: "other", href: null, label: contact.other.trim() };
  }
  return { kind: "none", href: null, label: EMPTY };
}

export function hasContact(contact) {
  return contactLink(contact).kind !== "none";
}

// ── Бренди ───────────────────────────────────────────────────────────────────

// Бренди рядка як масив рядків (пайплайн може віддати рядки або {name, normalized}).
export function brandNames(brands) {
  if (!Array.isArray(brands)) return [];
  const out = [];
  for (const b of brands) {
    const name = typeof b === "string" ? b : b && (b.normalized || b.name);
    if (typeof name === "string" && name.trim() && !out.includes(name.trim())) out.push(name.trim());
  }
  return out;
}

// Перші `max` брендів і лишок «+N».
export function brandsSummary(brands, max = 5) {
  const names = brandNames(brands);
  return { shown: names.slice(0, max), more: Math.max(0, names.length - max) };
}

export function uniqueBrands(rows) {
  const set = new Set();
  for (const r of rows ?? []) for (const b of brandNames(r.brands)) set.add(b);
  return [...set].sort((a, b) => a.localeCompare(b, "uk"));
}

export function uniqueClusters(keywords) {
  const out = [];
  for (const k of keywords ?? []) if (k.cluster && !out.includes(k.cluster)) out.push(k.cluster);
  return out;
}

// ── Позиції ──────────────────────────────────────────────────────────────────

// Ключі позицій рядка як рядки (JSON-ключі), відсортовані за числовим id.
export function positionKeywordIds(row) {
  const pos = row?.positions;
  if (!pos || typeof pos !== "object") return [];
  return Object.keys(pos)
    .filter((k) => Array.isArray(pos[k]) && pos[k].length > 0)
    .sort((a, b) => Number(a) - Number(b));
}

// Точки історії за датою (зростання), без сміття.
export function sortedPoints(points) {
  if (!Array.isArray(points)) return [];
  return points
    .filter((p) => p && typeof p.date === "string" && isNum(p.position))
    .slice()
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

// Остання відома позиція (за найпізнішою датою) або null.
export function latestPosition(points) {
  const s = sortedPoints(points);
  return s.length ? s[s.length - 1].position : null;
}

// Позиція на конкретну дату або null.
export function positionOn(points, date) {
  for (const p of sortedPoints(points)) if (p.date === date) return p.position;
  return null;
}

// Краща (мінімальна) позиція рядка: з поля або обчислена з історії.
export function bestPosition(row) {
  if (isNum(row?.best_position)) return row.best_position;
  let best = null;
  for (const k of positionKeywordIds(row)) {
    for (const p of sortedPoints(row.positions[k])) if (best == null || p.position < best) best = p.position;
  }
  return best;
}

// Геометрія спарклайна: Y інвертована (1 — вгорі), фіксована шкала min..max,
// точки рівномірно по X; одна точка — у центрі. Повертає {d, pts, last}.
export function sparklineGeometry(points, w = 60, h = 16, { min = 1, max = 10, pad = 3 } = {}) {
  const s = sortedPoints(points);
  if (!s.length) return { d: "", pts: [], last: null };
  const span = Math.max(1, max - min);
  const innerW = w - 2 * pad;
  const innerH = h - 2 * pad;
  const clamp = (v) => Math.min(max, Math.max(min, v));
  const pts = s.map((p, i) => {
    const x = s.length === 1 ? w / 2 : pad + (innerW * i) / (s.length - 1);
    const y = pad + ((clamp(p.position) - min) / span) * innerH;
    return { x: round1(x), y: round1(y), date: p.date, position: p.position };
  });
  const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  return { d, pts, last: pts[pts.length - 1] };
}

export function sparklinePath(points, w = 60, h = 16, opts) {
  return sparklineGeometry(points, w, h, opts).d;
}

function round1(v) {
  return Math.round(v * 10) / 10;
}

// Підпис для доступності: "#3: 4 → 2 (2026-11-03 … 2026-11-04)".
export function sparklineLabel(keywordId, points) {
  const s = sortedPoints(points);
  if (!s.length) return `#${keywordId}: ${EMPTY}`;
  const seq = s.map((p) => p.position).join(" → ");
  const range = s.length > 1 ? ` (${s[0].date} … ${s[s.length - 1].date})` : ` (${s[0].date})`;
  return `#${keywordId}: ${seq}${range}`;
}

// ── Фільтри ──────────────────────────────────────────────────────────────────

export const DEFAULT_FILTERS = Object.freeze({
  cluster: "",
  keywordId: "",
  siteType: "",
  brand: "",
  onlyRelevant: true,
  query: "",
});

export function keywordById(keywords, id) {
  return (keywords ?? []).find((k) => String(k.id) === String(id)) ?? null;
}

export function filterRows(rows, filters, keywords = []) {
  const f = { ...DEFAULT_FILTERS, ...(filters ?? {}) };
  const q = f.query.trim().toLowerCase();
  const clusterIds = f.cluster
    ? new Set(keywords.filter((k) => k.cluster === f.cluster).map((k) => String(k.id)))
    : null;
  return (rows ?? []).filter((r) => {
    if (f.onlyRelevant && r.relevant !== true) return false;
    if (f.siteType && r.site_type !== f.siteType) return false;
    const ids = positionKeywordIds(r);
    if (f.keywordId && !ids.includes(String(f.keywordId))) return false;
    if (clusterIds && !ids.some((id) => clusterIds.has(id))) return false;
    if (f.brand && !brandNames(r.brands).includes(f.brand)) return false;
    // Пошук — лише по домену (менеджеру потрібен домен, не шлях сторінки).
    if (q && !String(r.domain ?? "").toLowerCase().includes(q)) return false;
    return true;
  });
}

export function isDefaultFilters(filters) {
  const f = { ...DEFAULT_FILTERS, ...(filters ?? {}) };
  return Object.keys(DEFAULT_FILTERS).every((k) => f[k] === DEFAULT_FILTERS[k]);
}

// ── Сортування ───────────────────────────────────────────────────────────────

export const SORT_KEYS = Object.freeze(["domain", "site_type", "relevance", "best_position"]);

function cmpStr(a, b) {
  return String(a ?? "").localeCompare(String(b ?? ""), "uk");
}

// null/невідоме — завжди в кінці незалежно від напрямку.
function cmpNumNullLast(a, b, dir) {
  const an = isNum(a), bn = isNum(b);
  if (!an && !bn) return 0;
  if (!an) return 1;
  if (!bn) return -1;
  return dir * (a - b);
}

function relevanceRank(row) {
  const group = row.relevant === true ? 2 : row.relevant == null ? 1 : 0;
  return group * 10 + (isNum(row.confidence) ? row.confidence : 0);
}

// Стабільне сортування: key ∈ SORT_KEYS, dir ∈ "asc" | "desc". Повертає новий масив.
export function sortRows(rows, key = "best_position", dir = "asc") {
  const d = dir === "desc" ? -1 : 1;
  const list = (rows ?? []).map((r, i) => ({ r, i }));
  list.sort((x, y) => {
    let c = 0;
    switch (key) {
      case "domain":
        c = d * cmpStr(x.r.domain, y.r.domain);
        break;
      case "site_type":
        c = d * cmpStr(siteTypeLabel(x.r.site_type), siteTypeLabel(y.r.site_type));
        break;
      case "relevance": {
        // asc = найрелевантніші першими (так зручніше менеджеру); desc — навпаки.
        // Ранг: релевантні (2) → не розмічені (1, ще можуть виявитись корисними) → нерелевантні (0).
        c = d * (relevanceRank(y.r) - relevanceRank(x.r));
        break;
      }
      case "best_position":
      default:
        c = cmpNumNullLast(bestPosition(x.r), bestPosition(y.r), d);
        break;
    }
    if (c === 0) c = cmpNumNullLast(bestPosition(x.r), bestPosition(y.r), 1);
    if (c === 0) c = cmpStr(x.r.domain, y.r.domain);
    return c !== 0 ? c : x.i - y.i;
  });
  return list.map((x) => x.r);
}

// Напрямок після кліку: інший ключ → типовий для нього; той самий → перемкнути.
export function nextSort(current, key) {
  const defaults = { domain: "asc", site_type: "asc", relevance: "asc", best_position: "asc" };
  if (!current || current.key !== key) return { key, dir: defaults[key] ?? "asc" };
  return { key, dir: current.dir === "asc" ? "desc" : "asc" };
}

// ── Історія позицій ──────────────────────────────────────────────────────────

// Для кожного ключа — топ-N релевантних URL за останньою позицією з позиціями по датах.
export function historyMatrix(rows, keywords, runDates, topN = 3) {
  const dates = Array.isArray(runDates) ? runDates.slice().sort() : [];
  const out = [];
  for (const k of keywords ?? []) {
    const id = String(k.id);
    const items = [];
    for (const r of rows ?? []) {
      if (r.relevant !== true) continue;
      const pts = r.positions?.[id];
      if (!Array.isArray(pts) || !pts.length) continue;
      const byDate = dates.map((dt) => positionOn(pts, dt));
      const latest = latestPosition(pts);
      const prev = dates.length > 1 ? positionOn(pts, dates[dates.length - 2]) : null;
      const cur = positionOn(pts, dates[dates.length - 1]);
      const delta = isNum(prev) && isNum(cur) ? prev - cur : null; // >0 — піднявся
      items.push({ domain: r.domain, url: r.url, byDate, latest, delta });
    }
    items.sort((a, b) => cmpNumNullLast(a.latest, b.latest, 1) || cmpStr(a.domain, b.domain));
    out.push({ keyword: k, items: items.slice(0, topN) });
  }
  return out;
}

// Дельта позиції → текст: +2 (піднявся на 2), −1, 0 → "=", null → "нова".
export function fmtDelta(delta) {
  if (!isNum(delta)) return "нова";
  if (delta === 0) return "=";
  return (delta > 0 ? "▲" : "▼") + Math.abs(delta);
}

// ── Підсумки ─────────────────────────────────────────────────────────────────

export function sumCost(runs) {
  let s = 0;
  for (const r of runs ?? []) if (isNum(r.cost_usd)) s += r.cost_usd;
  return Math.round(s * 100) / 100;
}

export function sortRunsDesc(runs) {
  return (runs ?? []).slice().sort((a, b) => cmpStr(b.date, a.date));
}

// Елемент помилки прогону → текст (рядок або {url, error}).
export function errorText(e) {
  if (e == null) return EMPTY;
  if (typeof e === "string") return e;
  if (typeof e === "object") {
    const parts = [];
    for (const k of ["keyword", "url", "stage", "error", "message"]) if (e[k]) parts.push(String(e[k]));
    return parts.length ? parts.join(": ") : JSON.stringify(e);
  }
  return String(e);
}

// Відсоток релевантних для KPI: беремо relevant_pct (0..100), інакше обчислюємо з relevant/urls.
export function relevantPct(kpi) {
  if (isNum(kpi?.relevant_pct)) return kpi.relevant_pct;
  if (isNum(kpi?.relevant) && isNum(kpi?.urls) && kpi.urls > 0) return (kpi.relevant / kpi.urls) * 100;
  return null;
}

// Параметр ?data= — лише відносний шлях у межах сайту; інакше типовий.
export function resolveDataPath(search, fallback = "./data/report.json") {
  const params = new URLSearchParams(search ?? "");
  const v = (params.get("data") ?? "").trim();
  if (!v) return fallback;
  if (/^[a-z][a-z0-9+.-]*:/i.test(v) || v.startsWith("//") || v.includes("..")) return fallback;
  return v;
}

// ── Бари і домени ────────────────────────────────────────────────────────────

// Частка бару 0..1 від максимуму; ненульове значення не буває тоншим за 1 %.
// CSS множить її на ширину треку без місця під число, тож 100 % бар не виштовхує підпис.
export function barShare(value, max) {
  if (!isNum(value) || value <= 0) return 0;
  const m = isNum(max) && max > 0 ? max : value;
  return Math.min(1, Math.max(0.01, value / m));
}

// Домен → частини з крапкою в кінці: "www.askgamblers.com" → ["www.", "askgamblers.", "com"].
// Між частинами DOM ставить <wbr>: довгий домен переноситься лише після крапки, не посеред слова.
export function domainParts(domain) {
  return partsAfter(domain, ".");
}

// Текст → частини, кожна (крім останньої) закінчується роздільником `sep`:
// partsAfter("оглядач/афіліат", "/") → ["оглядач/", "афіліат"]. Між ними DOM ставить <wbr>.
export function partsAfter(text, sep) {
  const t = String(text ?? "");
  if (!t) return [];
  const out = [];
  let start = 0;
  for (let i = t.indexOf(sep); i !== -1; i = t.indexOf(sep, i + sep.length)) {
    out.push(t.slice(start, i + sep.length));
    start = i + sep.length;
  }
  if (start < t.length) out.push(t.slice(start));
  return out;
}

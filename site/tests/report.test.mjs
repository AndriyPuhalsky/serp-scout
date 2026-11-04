// Тести чистих функцій сайту-звіту: node --test site/tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import {
  EMPTY,
  fmtInt, fmtPct, fmtRatioPct, fmtUsd, fmtDate, fmtDateTime, orDash,
  siteTypeLabel, runStatusLabel, pluralUk, isLabeled, countUnlabeled,
  safeHref, safeMailto, contactLink, hasContact,
  brandNames, brandsSummary, uniqueBrands, uniqueClusters,
  positionKeywordIds, latestPosition, positionOn, bestPosition,
  sparklineGeometry, sparklinePath, sparklineLabel,
  filterRows, isDefaultFilters, DEFAULT_FILTERS,
  sortRows, nextSort,
  historyMatrix, fmtDelta, sumCost, sortRunsDesc, errorText, relevantPct, resolveDataPath,
} from "../js/report.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const report = JSON.parse(readFileSync(join(here, "fixtures/report.sample.json"), "utf8"));
const { rows, keywords, run_dates } = report;

test("фікстура має очікувану структуру report.json", () => {
  for (const k of ["generated_at", "run_dates", "latest_run", "kpi", "keywords", "rows", "brands_top", "runs"]) {
    assert.ok(k in report, `немає поля ${k}`);
  }
  assert.equal(keywords.length, 10);
  assert.equal(run_dates.length, 2);
  assert.ok(rows.length >= 20);
  assert.equal(report.kpi.urls, rows.length);
  assert.equal(report.kpi.relevant, rows.filter((r) => r.relevant).length);
  for (const r of rows) {
    assert.equal(typeof r.url, "string");
    assert.equal(typeof r.relevant, "boolean");
    assert.ok(r.confidence >= 0 && r.confidence <= 1);
    assert.ok(Object.keys(r.positions).length > 0, `${r.domain} без позицій`);
  }
});

test("fmtInt: групування розрядів і порожні значення", () => {
  assert.equal(fmtInt(0), "0");
  assert.equal(fmtInt(26), "26");
  assert.equal(fmtInt(1234567), "1 234 567");
  assert.equal(fmtInt(null), EMPTY);
  assert.equal(fmtInt(NaN), EMPTY);
  assert.equal(fmtInt("12"), EMPTY);
});

test("fmtPct / fmtRatioPct: один знак, кома, нерозривний пробіл", () => {
  assert.equal(fmtPct(46.15), "46,2 %");
  assert.equal(fmtPct(100), "100,0 %");
  assert.equal(fmtRatioPct(0.95), "95,0 %");
  assert.equal(fmtRatioPct(0.5), "50,0 %");
  assert.equal(fmtPct(undefined), EMPTY);
});

test("fmtUsd: завжди два знаки, $0.00 для нуля, «—» для порожнього", () => {
  assert.equal(fmtUsd(0), "$0.00");
  assert.equal(fmtUsd(0.3), "$0.30");
  assert.equal(fmtUsd(0.275), "$0.28");
  assert.equal(fmtUsd(null), EMPTY);
});

test("fmtDate / fmtDateTime / orDash", () => {
  assert.equal(fmtDate("2026-11-04"), "2026-11-04");
  assert.equal(fmtDate("2026-11-04T07:12:41+00:00"), "2026-11-04");
  assert.equal(fmtDate(""), EMPTY);
  assert.match(fmtDateTime("2026-11-04T07:12:41+00:00"), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  assert.equal(fmtDateTime("не дата"), "не дата");
  assert.equal(orDash("  "), EMPTY);
  assert.equal(orDash(null), EMPTY);
  assert.equal(orDash("casino.ca"), "casino.ca");
});

test("підписи типів, статусів і множина", () => {
  assert.equal(siteTypeLabel("review_affiliate"), "оглядач/афіліат");
  assert.equal(siteTypeLabel("regulator_gov"), "регулятор");
  assert.equal(siteTypeLabel("щось_невідоме"), "інше");
  assert.equal(runStatusLabel("budget_exceeded"), "бюджет вичерпано");
  assert.equal(runStatusLabel(null), EMPTY);
  assert.equal(pluralUk(1, ["сторінка", "сторінки", "сторінок"]), "сторінка");
  assert.equal(pluralUk(3, ["сторінка", "сторінки", "сторінок"]), "сторінки");
  assert.equal(pluralUk(7, ["сторінка", "сторінки", "сторінок"]), "сторінок");
  assert.equal(pluralUk(11, ["сторінка", "сторінки", "сторінок"]), "сторінок");
  assert.equal(pluralUk(22, ["сторінка", "сторінки", "сторінок"]), "сторінки");
});

test("safeHref і safeMailto блокують небезпечні схеми", () => {
  assert.equal(safeHref("https://www.casino.ca/"), "https://www.casino.ca/");
  assert.equal(safeHref("javascript:alert(1)"), null);
  assert.equal(safeHref("data:text/html,hi"), null);
  assert.equal(safeHref("//evil.example"), null);
  assert.equal(safeHref(null), null);
  assert.equal(safeMailto("partners@casino.ca"), "mailto:partners@casino.ca");
  assert.equal(safeMailto("not an email"), null);
  assert.equal(safeMailto('a"b@x.y'), null);
});

test("contactLink: пріоритет email → сторінка → telegram → форма → інше → «—»", () => {
  assert.deepEqual(contactLink({ email: "ads@x.ca", contact_page: "https://x.ca/c" }),
    { kind: "mailto", href: "mailto:ads@x.ca", label: "ads@x.ca" });
  assert.deepEqual(contactLink({ email: null, contact_page: "https://x.ca/c" }),
    { kind: "page", href: "https://x.ca/c", label: "сторінка" });
  assert.deepEqual(contactLink({ telegram: "@casinoreviews_ads" }),
    { kind: "telegram", href: "https://t.me/casinoreviews_ads", label: "@casinoreviews_ads" });
  assert.equal(contactLink({ form: true }).label, "форма на сайті");
  assert.equal(contactLink({ other: "Postmedia Content Works" }).kind, "other");
  assert.deepEqual(contactLink(null), { kind: "none", href: null, label: EMPTY });
  assert.deepEqual(contactLink({ email: null, contact_page: null, telegram: null, form: false, other: null }).label, EMPTY);
  assert.equal(hasContact({ form: true }), true);
  assert.equal(hasContact(null), false);
  // KPI «контактів» у фікстурі збігається з обчисленням по рядках.
  assert.equal(rows.filter((r) => hasContact(r.contact)).length, report.kpi.contacts);
});

test("бренди: нормалізація, ≤ 5 + «+N», унікальні", () => {
  assert.deepEqual(brandNames(["A", { name: "B" }, { name: "c", normalized: "C" }, "A", "", null]), ["A", "B", "C"]);
  const s = brandsSummary(["1", "2", "3", "4", "5", "6", "7"]);
  assert.deepEqual(s.shown, ["1", "2", "3", "4", "5"]);
  assert.equal(s.more, 2);
  assert.equal(brandsSummary([]).more, 0);
  assert.equal(uniqueBrands(rows).length, report.kpi.brands);
  assert.deepEqual(uniqueClusters(keywords), ["Грошові", "Рейтинги", "Платіжки", "Бездеп/фріспіни", "Грошові (провінція)"]);
});

test("позиції: ключі за id, остання, на дату, краща", () => {
  const casinoCa = rows.find((r) => r.domain === "casino.ca");
  assert.deepEqual(positionKeywordIds(casinoCa), ["1", "2", "3", "10"]);
  assert.equal(latestPosition(casinoCa.positions["1"]), 2);
  assert.equal(positionOn(casinoCa.positions["1"], "2026-11-03"), 3);
  assert.equal(positionOn(casinoCa.positions["1"], "2026-01-01"), null);
  assert.equal(bestPosition(casinoCa), 1);
  assert.equal(bestPosition({ positions: { 7: [{ date: "2026-11-04", position: 6 }] } }), 6);
  assert.equal(bestPosition({ positions: {} }), null);
  assert.equal(latestPosition([]), null);
  // Невідсортовані точки сортуються за датою.
  assert.equal(latestPosition([{ date: "2026-11-04", position: 2 }, { date: "2026-11-03", position: 9 }]), 2);
});

test("sparklineGeometry: Y інвертована (1 — вгорі), шкала 1..10, одна точка — по центру", () => {
  const g = sparklineGeometry([{ date: "2026-11-03", position: 10 }, { date: "2026-11-04", position: 1 }], 60, 16);
  assert.equal(g.pts.length, 2);
  assert.equal(g.pts[0].x, 3);
  assert.equal(g.pts[0].y, 13); // позиція 10 — внизу
  assert.equal(g.pts[1].x, 57);
  assert.equal(g.pts[1].y, 3); // позиція 1 — вгорі
  assert.equal(g.d, "M3,13 L57,3");
  assert.equal(g.last.position, 1);
  const one = sparklineGeometry([{ date: "2026-11-04", position: 5 }], 60, 16);
  assert.equal(one.pts[0].x, 30);
  assert.equal(one.d, "M30,7.4");
  assert.equal(sparklinePath([], 60, 16), "");
  // Позиції > 10 обрізаються до низу шкали, порядок дат не важливий.
  const clamped = sparklineGeometry([{ date: "2026-11-04", position: 14 }, { date: "2026-11-03", position: 1 }], 60, 16);
  assert.equal(clamped.pts[0].y, 3);
  assert.equal(clamped.pts[1].y, 13);
  assert.equal(sparklineLabel(3, [{ date: "2026-11-03", position: 4 }, { date: "2026-11-04", position: 2 }]),
    "#3: 4 → 2 (2026-11-03 … 2026-11-04)");
  assert.equal(sparklineLabel(3, []), `#3: ${EMPTY}`);
});

test("filterRows: типово лише релевантні; кластер, ключ, тип, бренд, пошук", () => {
  assert.equal(filterRows(rows, DEFAULT_FILTERS, keywords).length, report.kpi.relevant);
  assert.equal(filterRows(rows, { onlyRelevant: false }, keywords).length, rows.length);
  const payments = filterRows(rows, { cluster: "Платіжки" }, keywords);
  assert.ok(payments.length > 0);
  for (const r of payments) assert.ok(positionKeywordIds(r).some((id) => ["6", "7"].includes(id)));
  const kw10 = filterRows(rows, { onlyRelevant: false, keywordId: 10 }, keywords);
  for (const r of kw10) assert.ok("10" in r.positions);
  const ops = filterRows(rows, { onlyRelevant: false, siteType: "casino_operator" }, keywords);
  assert.ok(ops.length > 0 && ops.every((r) => r.site_type === "casino_operator"));
  const jc = filterRows(rows, { onlyRelevant: false, brand: "JackpotCity" }, keywords);
  assert.equal(jc.length, report.brands_top.find((b) => b.brand === "JackpotCity").pages);
  assert.deepEqual(filterRows(rows, { query: "  CASINO.ORG " }, keywords).map((r) => r.domain), ["casino.org"]);
  assert.equal(filterRows(rows, { query: "немає-такого" }, keywords).length, 0);
  // Пошук — лише по домену: «sponsored» є в шляху torontosun.com, але не в домені.
  assert.equal(filterRows(rows, { onlyRelevant: false, query: "sponsored" }, keywords).length, 0);
  assert.equal(filterRows(rows, { onlyRelevant: false, query: "torontosun" }, keywords).length, 1);
  assert.equal(isDefaultFilters({}), true);
  assert.equal(isDefaultFilters({ query: "x" }), false);
});

test("sortRows: краща позиція (null у кінці), домен, тип, релевантність; стабільність", () => {
  const byPos = sortRows(rows, "best_position", "asc");
  assert.equal(bestPosition(byPos[0]), 1);
  const nulls = sortRows([{ domain: "b", best_position: null }, { domain: "a", best_position: 3 }], "best_position", "desc");
  assert.equal(nulls[0].domain, "a");
  assert.equal(nulls[1].domain, "b");
  const byDomain = sortRows(rows, "domain", "asc").map((r) => r.domain);
  assert.deepEqual(byDomain, byDomain.slice().sort((a, b) => a.localeCompare(b, "uk")));
  const byDomainDesc = sortRows(rows, "domain", "desc").map((r) => r.domain);
  assert.equal(byDomainDesc[0], byDomain[byDomain.length - 1]);
  const byType = sortRows(rows, "site_type", "asc");
  assert.equal(byType[0].site_type, "encyclopedia"); // «енциклопедія» перша за алфавітом
  const byRel = sortRows(rows, "relevance", "asc");
  assert.equal(byRel[0].relevant, true);
  assert.equal(byRel[byRel.length - 1].relevant, false);
  assert.ok(byRel[0].confidence >= byRel[1].confidence);
  assert.notEqual(sortRows(rows, "domain"), rows, "повертає новий масив");
  assert.deepEqual(nextSort(null, "domain"), { key: "domain", dir: "asc" });
  assert.deepEqual(nextSort({ key: "domain", dir: "asc" }, "domain"), { key: "domain", dir: "desc" });
  assert.deepEqual(nextSort({ key: "domain", dir: "desc" }, "relevance"), { key: "relevance", dir: "asc" });
});

test("historyMatrix: топ-3 релевантних на ключ, позиції по датах, дельта", () => {
  const m = historyMatrix(rows, keywords, run_dates, 3);
  assert.equal(m.length, 10);
  for (const g of m) {
    assert.ok(g.items.length <= 3);
    for (const it of g.items) assert.equal(it.byDate.length, 2);
  }
  const kw1 = m.find((g) => g.keyword.id === 1);
  assert.equal(kw1.items[0].domain, "casino.org"); // позиція 1 на останню дату
  const cc = kw1.items.find((it) => it.domain === "casino.ca");
  assert.deepEqual(cc.byDate, [3, 2]);
  assert.equal(cc.delta, 1); // піднявся з 3 на 2
  assert.equal(fmtDelta(1), "▲1");
  assert.equal(fmtDelta(-2), "▼2");
  assert.equal(fmtDelta(0), "=");
  assert.equal(fmtDelta(null), "нова");
  const kw4 = m.find((g) => g.keyword.id === 4);
  const fresh = kw4.items.find((it) => it.domain === "casinoreviews.net");
  assert.deepEqual(fresh.byDate, [null, 2]);
  assert.equal(fresh.delta, null);
  // Одна дата — дельт немає, матриця з однією колонкою.
  const single = historyMatrix(rows, keywords, ["2026-11-04"], 3);
  assert.ok(single.every((g) => g.items.every((it) => it.byDate.length === 1 && it.delta === null)));
});

test("прогони: сума вартості, порядок, помилки, відсоток релевантних", () => {
  assert.equal(sumCost(report.runs), 0.29);
  assert.equal(sumCost([]), 0);
  assert.deepEqual(sortRunsDesc(report.runs).map((r) => r.date), ["2026-11-04", "2026-11-03"]);
  assert.equal(errorText("timeout"), "timeout");
  assert.equal(errorText({ url: "https://x.ca", error: "403" }), "https://x.ca: 403");
  assert.equal(errorText(null), EMPTY);
  assert.equal(relevantPct({ relevant_pct: 46.2 }), 46.2);
  assert.equal(relevantPct({ relevant: 1, urls: 4 }), 25);
  assert.equal(relevantPct({}), null);
});

test("не розмічені рядки (relevant: null): підпис, фільтр, сортування, лічильник", () => {
  const unl = { url: "https://x.ca/", domain: "x.ca", site_type: null, relevant: null, confidence: null, reason: "", brands: [], contact: {}, positions: { 6: [{ date: "2026-11-04", position: 1 }] }, best_position: 1, needs_review: true, method: null };
  assert.equal(isLabeled(unl), false);
  assert.equal(isLabeled(rows[0]), true);
  assert.equal(siteTypeLabel(null), "не розмічено");
  assert.equal(siteTypeLabel(undefined), "не розмічено");
  assert.equal(hasContact({}), false);
  assert.equal(fmtRatioPct(null), EMPTY);
  const mixed = [...rows, unl];
  assert.equal(countUnlabeled(mixed), 1);
  assert.equal(countUnlabeled(rows), 0);
  // Типовий фільтр «лише релевантні» ховає не розмічені.
  assert.equal(filterRows(mixed, DEFAULT_FILTERS, keywords).length, report.kpi.relevant);
  assert.equal(filterRows(mixed, { onlyRelevant: false }, keywords).length, mixed.length);
  // За релевантністю: релевантні → не розмічені → нерелевантні.
  const sorted = sortRows(mixed, "relevance", "asc");
  const idx = sorted.findIndex((r) => r.relevant === null);
  assert.ok(sorted.slice(0, idx).every((r) => r.relevant === true));
  assert.ok(sorted.slice(idx + 1).every((r) => r.relevant === false));
});

test("resolveDataPath: лише відносний шлях у межах сайту", () => {
  assert.equal(resolveDataPath(""), "./data/report.json");
  assert.equal(resolveDataPath("?data=tests/fixtures/report.sample.json"), "tests/fixtures/report.sample.json");
  assert.equal(resolveDataPath("?data=https://evil.example/x.json"), "./data/report.json");
  assert.equal(resolveDataPath("?data=//evil.example/x.json"), "./data/report.json");
  assert.equal(resolveDataPath("?data=../../etc/passwd"), "./data/report.json");
  assert.equal(resolveDataPath("?data=javascript:alert(1)"), "./data/report.json");
});

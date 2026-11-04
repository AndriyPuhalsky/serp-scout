#!/usr/bin/env node
// Скріншоти для методички маркетолога (docs/09, Р-010, Р-025).
// Headless Chrome через CDP на вбудованому WebSocket Node ≥ 22 — без Playwright/puppeteer і npm-залежностей.
//
// Вхід: site/guide/shots.json — масив {out, url, selector?, click?, wait?, scale?, maxHeight?}.
//   out       — шлях PNG відносно теки конфігу (типово site/guide/) або --out-dir;
//   url       — абсолютний або відносний до BASE_URL (типово https://serp-scout.netlify.app);
//   selector  — CSS-селектор елемента для clip; без нього — знімок вікна 1280×900;
//   click     — CSS-селектор, по якому клікнути перед знімком (відкрити «чому», фільтр);
//   wait      — пауза після завантаження, мс (типово 800);
//   scale     — масштаб clip (типово 1; 0.75 зменшує PNG);
//   maxHeight — обрізати clip за висотою, CSS px (типово 1400).
//
// Запуск: node tools/guide_shots.mjs [--config шлях] [--base URL] [--out-dir тека] [--only підрядок]
// Змінні: CHROME_BIN (шлях до Chrome), BASE_URL.
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CHROME_BIN = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const NAV_TIMEOUT_MS = 20_000;
const START_TIMEOUT_MS = 15_000;
const WIDTH = 1280;
const HEIGHT = 900;
const SIZE_LIMIT = 200 * 1024;

// --- аргументи командного рядка ---
function parseArgs(argv) {
  const opts = {
    config: join(ROOT, "site/guide/shots.json"),
    base: process.env.BASE_URL || "https://serp-scout.netlify.app",
    outDir: null,
    only: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => {
      if (i + 1 >= argv.length) fail(`Прапорець ${a} потребує значення.`);
      return argv[++i];
    };
    if (a === "--config") opts.config = resolve(next());
    else if (a === "--base") opts.base = next();
    else if (a === "--out-dir") opts.outDir = resolve(next());
    else if (a === "--only") opts.only = next();
    else if (a === "-h" || a === "--help") {
      console.log("Використання: node tools/guide_shots.mjs [--config шлях] [--base URL] [--out-dir тека] [--only підрядок]");
      process.exit(0);
    } else fail(`Невідомий аргумент: ${a}`);
  }
  opts.outDir ??= dirname(opts.config);
  return opts;
}

function fail(msg, code = 2) {
  console.error(`Помилка: ${msg}`);
  process.exit(code);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Вільний TCP-порт: слухаємо 0, беремо призначений порт і звільняємо.
function freePort() {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", rej);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => res(port));
    });
  });
}

// --- мінімальний CDP-клієнт (flatten-сесії через sessionId) ---
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Set();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(typeof ev.data === "string" ? ev.data : Buffer.from(ev.data).toString());
      if (msg.id !== undefined) {
        const p = this.pending.get(msg.id);
        if (!p) return;
        this.pending.delete(msg.id);
        if (msg.error) p.reject(new Error(`${p.method}: ${msg.error.message}`));
        else p.resolve(msg.result);
      } else {
        for (const l of this.listeners) l(msg);
      }
    });
    ws.addEventListener("close", () => {
      for (const p of this.pending.values()) p.reject(new Error("з'єднання з Chrome закрито"));
      this.pending.clear();
    });
  }

  static connect(url) {
    return new Promise((res, rej) => {
      const ws = new WebSocket(url);
      ws.addEventListener("open", () => res(new Cdp(ws)), { once: true });
      ws.addEventListener("error", () => rej(new Error(`не вдалося під'єднатися до ${url}`)), { once: true });
    });
  }

  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject, method });
      this.ws.send(JSON.stringify(msg));
    });
  }

  // Чекаємо подію method у сесії sessionId не довше timeout мс.
  waitFor(method, sessionId, timeout, timeoutMsg) {
    return new Promise((resolve, reject) => {
      const l = (msg) => {
        if (msg.method === method && msg.sessionId === sessionId) {
          clearTimeout(t);
          this.listeners.delete(l);
          resolve(msg.params);
        }
      };
      const t = setTimeout(() => {
        this.listeners.delete(l);
        reject(new Error(timeoutMsg || `таймаут ${timeout} мс очікування ${method}`));
      }, timeout);
      this.listeners.add(l);
    });
  }

  close() {
    try { this.ws.close(); } catch {}
  }
}

// --- запуск Chrome ---
async function startChrome() {
  if (!existsSync(CHROME_BIN)) {
    fail(`не знайдено Chrome за шляхом «${CHROME_BIN}». Встановіть Google Chrome або задайте змінну CHROME_BIN.`);
  }
  const port = await freePort();
  const profile = await mkdtemp(join(tmpdir(), "serp-scout-shots-"));
  const proc = spawn(CHROME_BIN, [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--window-size=${WIDTH},${HEIGHT}`,
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--mute-audio",
    "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  proc.stderr.on("data", (d) => { stderr = (stderr + d).slice(-2000); });
  const spawnErr = new Promise((_, rej) => proc.once("error", (e) => rej(new Error(`не вдалося запустити Chrome: ${e.message}`))));

  const chrome = { proc, profile, port };
  // Чекаємо, поки DevTools-ендпоінт відповість.
  const deadline = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      await stopChrome(chrome);
      fail(`Chrome завершився з кодом ${proc.exitCode} до старту DevTools.\n${stderr.trim()}`);
    }
    try {
      const r = await Promise.race([fetch(`http://127.0.0.1:${port}/json/version`), spawnErr]);
      if (r.ok) {
        const { webSocketDebuggerUrl } = await r.json();
        chrome.wsUrl = webSocketDebuggerUrl;
        return chrome;
      }
    } catch (e) {
      if (e.message.startsWith("не вдалося запустити")) { await stopChrome(chrome); fail(e.message); }
    }
    await sleep(150);
  }
  await stopChrome(chrome);
  fail(`Chrome не відкрив DevTools-порт ${port} за ${START_TIMEOUT_MS / 1000} с.\n${stderr.trim()}`);
}

// Зупинка Chrome: SIGTERM, через 3 с — SIGKILL; потім прибираємо тимчасовий профіль.
async function stopChrome(chrome) {
  const { proc } = chrome;
  if (proc.exitCode === null && proc.signalCode === null) {
    const exited = new Promise((r) => proc.once("exit", r));
    proc.kill("SIGTERM");
    const ok = await Promise.race([exited.then(() => true), sleep(3000).then(() => false)]);
    if (!ok) { proc.kill("SIGKILL"); await Promise.race([exited, sleep(2000)]); }
  }
  await rm(chrome.profile, { recursive: true, force: true }).catch(() => {});
}

// --- один знімок ---
async function evaluate(cdp, sessionId, expression) {
  const r = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
  if (r.exceptionDetails) {
    throw new Error(`помилка JS на сторінці: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
  }
  return r.result.value;
}

async function shoot(cdp, shot, opts) {
  const url = new URL(shot.url, opts.base.endsWith("/") ? opts.base : opts.base + "/").href;
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  try {
    await cdp.send("Page.enable", {}, sessionId);
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false }, sessionId);
    // Світла тема і без анімацій: прапорець у localStorage до скриптів сайту + медіа-ознаки.
    await cdp.send("Emulation.setEmulatedMedia", {
      features: [
        { name: "prefers-color-scheme", value: "light" },
        { name: "prefers-reduced-motion", value: "reduce" },
      ],
    }, sessionId);
    await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
      source: 'try { localStorage.setItem("theme", "light"); } catch (e) {}',
    }, sessionId);

    const loaded = cdp.waitFor("Page.loadEventFired", sessionId, NAV_TIMEOUT_MS,
      `таймаут ${NAV_TIMEOUT_MS / 1000} с: сторінка ${url} не завантажилась`);
    loaded.catch(() => {});
    const nav = await cdp.send("Page.navigate", { url }, sessionId);
    if (nav.errorText) throw new Error(`не вдалося відкрити ${url}: ${nav.errorText}`);
    await loaded;
    await evaluate(cdp, sessionId, "document.fonts ? document.fonts.ready.then(() => true) : true");
    await sleep(shot.wait ?? 800);

    if (shot.click) {
      const found = await evaluate(cdp, sessionId,
        `(() => { const el = document.querySelector(${JSON.stringify(shot.click)});
          if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`);
      if (!found) throw new Error(`не знайдено елемент для кліку «${shot.click}»`);
      await sleep(400);
    }

    let params = { format: "png" };
    if (shot.selector) {
      // Прокручуємо до елемента, щоб спрацювали ліниві reveal-ефекти, і беремо рамку в координатах документа.
      const sel = JSON.stringify(shot.selector);
      const ok = await evaluate(cdp, sessionId,
        `(() => { const el = document.querySelector(${sel}); if (!el) return false;
          el.scrollIntoView({ block: "start" }); return true; })()`);
      if (!ok) throw new Error(`не знайдено селектор «${shot.selector}» на ${url}`);
      await sleep(400);
      const box = await evaluate(cdp, sessionId,
        `(() => { const r = document.querySelector(${sel}).getBoundingClientRect();
          return { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height }; })()`);
      if (!box || box.w < 1 || box.h < 1) throw new Error(`елемент «${shot.selector}» невидимий (нульовий розмір)`);
      const maxH = shot.maxHeight ?? 1400;
      params = {
        format: "png",
        captureBeyondViewport: true,
        clip: {
          x: Math.max(0, Math.floor(box.x)),
          y: Math.max(0, Math.floor(box.y)),
          width: Math.ceil(box.w),
          height: Math.min(Math.ceil(box.h), maxH),
          scale: shot.scale ?? 1,
        },
      };
    } else if (shot.scale && shot.scale !== 1) {
      params.clip = { x: 0, y: 0, width: WIDTH, height: HEIGHT, scale: shot.scale };
    }
    const { data } = await cdp.send("Page.captureScreenshot", params, sessionId);
    const buf = Buffer.from(data, "base64");
    const outPath = resolve(opts.outDir, shot.out);
    await mkdir(dirname(outPath), { recursive: true });
    await writeFile(outPath, buf);
    return { outPath, bytes: buf.length };
  } finally {
    await cdp.send("Target.closeTarget", { targetId }).catch(() => {});
  }
}

// --- головний цикл ---
async function main() {
  const opts = parseArgs(process.argv.slice(2));
  let shots;
  try {
    shots = JSON.parse(await readFile(opts.config, "utf8"));
  } catch (e) {
    fail(e.code === "ENOENT" ? `не знайдено файл конфігу ${opts.config}` : `не вдалося прочитати ${opts.config}: ${e.message}`);
  }
  if (!Array.isArray(shots)) fail(`${opts.config} має містити масив записів {out, url, ...}`);
  if (opts.only) shots = shots.filter((s) => String(s.out).includes(opts.only));
  if (!shots.length) fail("немає жодного запису для знімка");

  const chrome = await startChrome();
  const onSignal = async () => { await stopChrome(chrome); process.exit(130); };
  process.once("SIGINT", onSignal);
  process.once("SIGTERM", onSignal);

  let cdp;
  const done = [], skipped = [];
  try {
    cdp = await Cdp.connect(chrome.wsUrl);
    for (const shot of shots) {
      const name = shot?.out || "(без out)";
      if (!shot?.out || !shot?.url) {
        skipped.push(name);
        console.error(`ПРОПУЩЕНО ${name}: у записі мають бути поля out і url`);
        continue;
      }
      try {
        const { outPath, bytes } = await shoot(cdp, shot, opts);
        const kb = (bytes / 1024).toFixed(0);
        const warn = bytes > SIZE_LIMIT ? `  УВАГА: більше 200 КБ — зменште clip (maxHeight) або scale` : "";
        console.log(`OK ${name}  ${kb} КБ  → ${outPath}${warn}`);
        done.push(name);
      } catch (e) {
        skipped.push(name);
        console.error(`ПРОПУЩЕНО ${name}: ${e.message}`);
      }
    }
  } finally {
    if (cdp) {
      await cdp.send("Browser.close").catch(() => {});
      cdp.close();
    }
    await stopChrome(chrome);
  }
  console.log(`Підсумок: зроблено ${done.length}, пропущено ${skipped.length}${skipped.length ? ` (${skipped.join(", ")})` : ""}.`);
  process.exit(skipped.length ? 1 : 0);
}

main().catch((e) => fail(e.message));

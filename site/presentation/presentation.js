// Навігація презентацією: ← → / пробіл / PageUp / PageDown / Home / End, хеш #N, лічильник «N / M».
// Режим слайдів — лише на широкому й високому екрані; на вузькому сторінка читається як документ.

const root = document.documentElement;
const slides = Array.from(document.querySelectorAll(".slide"));
const total = slides.length;
const cur = document.getElementById("p-cur");
const prevBtn = document.querySelector('[data-go="prev"]');
const nextBtn = document.querySelector('[data-go="next"]');
document.getElementById("p-total").textContent = String(total);

const deckQuery = window.matchMedia("(min-width: 900px) and (min-height: 560px)");
let index = 0;

// Номер слайда з хешу «#N» (1..total); інакше 0.
function fromHash() {
  const n = Number.parseInt(location.hash.slice(1), 10);
  return Number.isInteger(n) && n >= 1 && n <= total ? n - 1 : 0;
}

function show(i, { updateHash = true } = {}) {
  index = Math.max(0, Math.min(total - 1, i));
  slides.forEach((s, k) => {
    const active = k === index;
    s.classList.toggle("is-active", active);
    if (root.classList.contains("is-deck")) s.toggleAttribute("inert", !active);
    else s.removeAttribute("inert");
  });
  cur.textContent = String(index + 1);
  prevBtn.disabled = index === 0;
  nextBtn.disabled = index === total - 1;
  if (updateHash && location.hash !== `#${index + 1}`) history.replaceState(null, "", `#${index + 1}`);
  if (root.classList.contains("is-deck")) slides[index].scrollTop = 0;
}

function applyMode() {
  const deck = deckQuery.matches && !window.matchMedia("print").matches;
  root.classList.toggle("is-deck", deck);
  show(index, { updateHash: false });
  if (!deck && location.hash) slides[index].scrollIntoView();
}

prevBtn.addEventListener("click", () => show(index - 1));
nextBtn.addEventListener("click", () => show(index + 1));

document.addEventListener("keydown", (ev) => {
  if (!root.classList.contains("is-deck") || ev.altKey || ev.ctrlKey || ev.metaKey) return;
  const tag = ev.target instanceof Element ? ev.target.tagName : "";
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  const isActivatable = tag === "BUTTON" || tag === "A";
  let next = null;
  if (ev.key === "ArrowRight" || ev.key === "PageDown") next = index + 1;
  else if (ev.key === "ArrowLeft" || ev.key === "PageUp") next = index - 1;
  else if (ev.key === " " && !isActivatable) next = ev.shiftKey ? index - 1 : index + 1;
  else if (ev.key === "Home") next = 0;
  else if (ev.key === "End") next = total - 1;
  if (next === null) return;
  ev.preventDefault();
  show(next);
});

window.addEventListener("hashchange", () => show(fromHash(), { updateHash: false }));
deckQuery.addEventListener("change", applyMode);

// Друк: усі слайди видимі (CSS), режим слайдів повертається після друку.
window.addEventListener("beforeprint", () => { root.classList.remove("is-deck"); slides.forEach((s) => s.removeAttribute("inert")); });
window.addEventListener("afterprint", applyMode);

// Тема: той самий ключ localStorage, що й у звіті.
document.getElementById("theme-toggle").addEventListener("click", () => {
  const t = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", t);
  try { localStorage.setItem("theme", t); } catch (e) { /* приватний режим */ }
});

index = fromHash();
applyMode();

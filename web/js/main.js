// Shell: routing on real paths (history API), the dateline in the masthead, the theme switch,
// and a periodic refresh.
import { abortAll, getJSON } from "./api.js";
import { hideTip } from "./chart.js";
import { dayOnly, esc, fmtTime, pct } from "./fmt.js";

const NAME = "Brazil fund flows";
const VIEWS = {
  "/": ["Overview", () => import("./views/overview.js")],
  "/flows": ["Flows", () => import("./views/flows.js")],
  "/reporting": ["Reporting", () => import("./views/reporting.js")],
  "/status": ["Status", () => import("./views/status.js")],
  "/method": ["Method", () => import("./views/method.js")],
};
const REFRESH_MS = 10 * 60e3;
const main = document.getElementById("view");
let current = null, timer = 0;

// URL query <-> view state, checked against each view's allowed values.
export function readState(allowed) {
  const q = new URLSearchParams(location.search), out = {};
  for (const [key, values, fallback] of allowed) {
    const v = q.get(key);
    out[key] = v != null && values.includes(v) ? v : fallback;
  }
  return out;
}
export function writeState(state) {
  const q = new URLSearchParams(location.search);
  Object.entries(state).forEach(([k, v]) => (v == null ? q.delete(k) : q.set(k, v)));
  history.replaceState(history.state, "", `${location.pathname}${q.toString() ? `?${q}` : ""}`);
}

async function route() {
  abortAll();
  hideTip();
  current?.stop?.();
  const path = location.pathname in VIEWS ? location.pathname : "/";
  const [title, load] = VIEWS[path];
  document.title = path === "/" ? NAME : `${title} · ${NAME}`;
  document.querySelectorAll("nav.tabs a").forEach((a) => {
    if (a.getAttribute("href") === path) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  main.innerHTML = "";
  const mod = await load();
  current = mod.default(main, { readState, writeState }) || null;
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  if (a.getAttribute("href") !== location.pathname || location.search) history.pushState({}, "", a.getAttribute("href"));
  route().then(() => main.focus({ preventScroll: true }));
  window.scrollTo(0, 0);
});
window.addEventListener("popstate", route);

// The dateline: which CVM file the page reflects, when it was last read, how much of the latest
// mostly-reported day is in, and whether the collector is running.
const STATE_WORDS = { ok: "collector running", late: "collector late", failing: "collector not running" };
async function dateline() {
  const el = document.getElementById("dateline");
  try {
    const o = await getJSON("/api/overview", "dateline");
    window.dispatchEvent(new CustomEvent("overview", { detail: o }));
    const lag2 = (o.completeness || []).find((d) => d.lag === 2);
    el.innerHTML = [
      o.file_day ? `CVM file of ${esc(dayOnly(o.file_day))}` : "No CVM file read yet",
      `updated ${esc(fmtTime(o.as_of))} BRT`,
      lag2 ? `${esc(dayOnly(lag2.dt))}: ${esc(pct(lag2.share, 0))} of funds in` : "",
      `<span class="${o.collector.state === "ok" ? "" : "attention"}">${STATE_WORDS[o.collector.state] || esc(o.collector.state)}</span>`,
    ].filter(Boolean).join(" · ");
  } catch (e) {
    if (e?.name !== "AbortError") el.innerHTML = `<span class="attention">status unavailable</span>`;
  }
}

function tick() {
  if (document.hidden) return;
  dateline();
  current?.refresh?.();
}

// Theme: light by default; the switch names the theme it leads to and is remembered on this device.
const themeButton = document.getElementById("theme");
const isDark = () => (document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches);
const labelTheme = () => { themeButton.textContent = isDark() ? "Light" : "Dark"; };
themeButton.addEventListener("click", () => {
  document.documentElement.dataset.theme = isDark() ? "light" : "dark";
  try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch (e) { /* storage may be blocked */ }
  labelTheme();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", labelTheme);
labelTheme();

document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
route();
dateline();
clearInterval(timer);
timer = setInterval(tick, REFRESH_MS);

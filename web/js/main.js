// Shell: routing on real paths (history API), the status bar, the theme toggle, and refresh.
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

// Status bar: is the collector alive, which CVM file was read last, how much of the latest
// mostly-reported day is in.
const STATE_WORDS = { ok: "Collector running", late: "Collector late", failing: "Collector not running" };
async function status() {
  const el = document.getElementById("statusbar");
  try {
    const o = await getJSON("/api/overview", "statusbar");
    window.dispatchEvent(new CustomEvent("overview", { detail: o }));
    const c = o.collector;
    const lag2 = (o.completeness || []).find((d) => d.lag === 2);
    el.innerHTML = [
      `<span><span class="dot ${esc(c.state)}"></span>${STATE_WORDS[c.state] || esc(c.state)}</span>`,
      o.file_day ? `<span>CVM file of ${dayOnly(o.file_day)}</span>` : "",
      lag2 ? `<span>${dayOnly(lag2.dt)}: ${pct(lag2.share, 0)} of funds in</span>` : "",
      `<span class="muted">Page updated ${fmtTime(o.as_of)}</span>`,
    ].filter(Boolean).join("");
  } catch (e) {
    if (e?.name !== "AbortError") el.innerHTML = `<span><span class="dot failing"></span>Status unavailable</span>`;
  }
}

function tick() {
  if (document.hidden) return;
  status();
  current?.refresh?.();
}

// Theme: light by default; the toggle cycles light and dark and is remembered on this device.
document.getElementById("theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) { /* storage may be blocked */ }
});

document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
route();
status();
clearInterval(timer);
timer = setInterval(tick, REFRESH_MS);

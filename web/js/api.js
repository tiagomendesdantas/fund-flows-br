// Fetching with one AbortController per slot, so a newer request always wins, and a per-card error
// with a retry button instead of a page-wide failure.
import { esc } from "./fmt.js";

const controllers = new Map();

export async function getJSON(url, slot = url) {
  controllers.get(slot)?.abort();
  const ctl = new AbortController();
  controllers.set(slot, ctl);
  const r = await fetch(url, { signal: ctl.signal, headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export const isAbort = (e) => e?.name === "AbortError";

export function abortAll() {
  controllers.forEach((c) => c.abort());
  controllers.clear();
}

// Run render(); on failure, show the error in `el` with a retry button.
export async function fill(el, render) {
  if (!el) return;
  el.setAttribute("aria-busy", "true");
  try {
    await render();
  } catch (e) {
    if (isAbort(e)) return;
    el.innerHTML = `<p class="err">Could not load this part: ${esc(e.message)}<button type="button">Retry</button></p>`;
    el.querySelector("button").addEventListener("click", () => fill(el, render));
  } finally {
    el.removeAttribute("aria-busy");
  }
}

// A quiet placeholder while a part loads: a muted dash, no animation. Phrasing content, so it
// can sit inside a paragraph.
export const skeleton = (kind = "chart") => (kind === "chart"
  ? `<div class="placeholder" aria-hidden="true" style="min-height:220px">—</div>`
  : `<span class="placeholder" aria-hidden="true">—</span>`);

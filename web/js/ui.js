import { esc } from "./fmt.js";

// A row of toggle buttons; onPick(value) runs when one is pressed.
export function chips(el, options, current, onPick) {
  el.innerHTML = options.map(([v, label]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${v === current}">${esc(label)}</button>`).join("");
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    onPick(b.dataset.v);
  }));
}

export const tile = (k, v, unit, d) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}${unit ? `<small>${unit}</small>` : ""}</div><div class="d">${d}</div></div>`;

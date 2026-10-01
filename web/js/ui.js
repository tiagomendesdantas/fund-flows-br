import { esc } from "./fmt.js";

// A segmented text control: a small-caps label, then the options as text buttons; the current one
// is underlined. onPick(value) runs when one is pressed.
export function segmented(el, label, options, current, onPick) {
  el.innerHTML = `<span class="seg-label">${esc(label)}</span>${options.map(([v, text]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${v === current}">${esc(text)}</button>`).join("")}`;
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    onPick(b.dataset.v);
  }));
}

// One cell of the key-figures band: label, figure with its unit on one baseline, a one-line note.
export const figure = (label, value, unit, note) => `<div class="figure"><div class="k">${label}</div><div class="v">${value}${unit ? `<span class="u">${unit}</span>` : ""}</div><div class="d">${note}</div></div>`;

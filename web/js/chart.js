// Hand-drawn SVG charts: time series (stacked areas, lines, interval bands) and a small
// category chart. One y-axis per chart; direct labels on wide screens and a table view on every
// chart (some hues sit under 3:1 contrast on the light surface); tooltips by pointer, touch and
// keyboard; redrawn when the container is resized. Values are divided by opts.scale for display.
import { BRT_OFFSET_MS, esc, fmtDay, fmtDayTime, fmtTime, toDate } from "./fmt.js";

const DAY = 86400e3;
const HOUR = 3600e3;
const VARS = { "e-actual": "--ink", "e-forecast": "--forecast", "e-programme": "--programme", "e-rooftop": "--rooftop",
  "e-hydro": "--hydro", "e-thermal": "--thermal", "e-wind": "--wind", "e-solar": "--solar", band80: "--band80", band95: "--band95",
  "m-ensemble": "--forecast", "m-mstl_ets": "--thermal", "m-boosting": "--wind", "m-seasonal_naive": "--muted", "m-ons_programme": "--ink",
  "fill-1": "--hydro", "fill-2": "--thermal", "fill-3": "--wind", "fill-4": "--muted", "e-seq1": "--seq1", "e-seq2": "--seq2", "e-seq3": "--seq3", "e-seq4": "--seq4", "e-seq5": "--seq5", "e-seq6": "--seq6", "e-seq7": "--seq7",
  "e-in": "--in", "e-out": "--out", "e-assets": "--ink", "b-in": "--in", "b-out": "--out" };

export function legend(items) {
  return `<div class="legend">${items.map(({ name, cls, kind = "line" }) => {
    const style = kind === "box" ? `background:var(${VARS[cls]})` : `border-color:var(${VARS[cls]})`;
    return `<span><span class="sw ${kind}" style="${style}"></span>${esc(name)}</span>`;
  }).join("")}</div>`;
}

function niceStep(span, n) {
  const raw = span / n, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
}

function niceScale(lo, hi, n, zero) {
  if (zero) lo = Math.min(0, lo);
  if (!(hi > lo)) hi = lo + 1;
  const step = niceStep(hi - lo, n);
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = a; v <= b + step / 2; v += step) ticks.push(v);
  return [a, b, ticks];
}

const tipEl = () => document.getElementById("tooltip");
function showTip(html, clientX, clientY) {
  const tip = tipEl();
  tip.innerHTML = html;
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let left = clientX + 14, top = clientY + 14;
  if (left + w > window.innerWidth - 8) left = clientX - w - 14;
  if (top + h > window.innerHeight - 8) top = clientY - h - 14;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}
export function hideTip() { tipEl().style.display = "none"; }

const observers = new WeakMap();
function observe(el, redraw) {
  el._redraw = redraw;
  if (observers.has(el)) return;
  let w = el.clientWidth, raf = 0;
  const ro = new ResizeObserver(() => {
    if (Math.abs(el.clientWidth - w) < 2) return;
    w = el.clientWidth;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => el._redraw?.());
  });
  ro.observe(el);
  observers.set(el, ro);
}

// opts: { stack:[{name, cls, points:[[t, mw]]}], lines:[{name, cls, points}], bands:[{name, cls, points:[[t, lo, hi]]}],
//         zero, now (ms), height, labels (default true), unit ("GW"), aria }
export function timeChart(el, opts) {
  observe(el, () => drawTime(el, opts));
  drawTime(el, opts);
}

function drawTime(el, o) {
  const stack = o.stack || [], lines = o.lines || [], bands = o.bands || [];
  const stamps = new Set();
  [...stack, ...lines, ...bands].forEach((s) => s.points.forEach((p) => stamps.add(p[0])));
  const grid = [...stamps].sort().map((s) => [s, toDate(s).getTime()]);
  if (!grid.length) { el.innerHTML = `<p class="small muted">No data yet.</p>`; return; }
  const width = Math.max(el.clientWidth || 640, 280), narrow = width < 560;
  const height = o.height || (narrow ? 230 : 290);
  const labels = o.labels !== false && !narrow;
  const longest = Math.max(0, ...stack.map((x) => x.name.length), ...lines.map((x) => x.name.length));
  const m = { l: 40, r: labels ? Math.min(170, 16 + longest * 6.6) : 12, t: 24, b: 26 };
  const at = (series) => { const map = new Map(series.points.map((p) => [p[0], p])); return grid.map(([s]) => map.get(s)); };

  const stackVals = [], base = grid.map(() => 0);
  stack.forEach((s) => {
    const pts = at(s);
    const lower = base.slice();
    pts.forEach((p, i) => { base[i] += p && p[1] != null ? p[1] : 0; });
    stackVals.push({ lower, upper: base.slice(), raw: pts.map((p) => (p ? p[1] : null)) });
  });
  const lineVals = lines.map((l) => at(l).map((p) => (p ? p[1] : null)));
  const bandVals = bands.map((b) => at(b).map((p) => (p ? [p[1], p[2]] : null)));
  const all = [...base.filter((v, i) => stack.length && v != null && i >= 0), ...lineVals.flat(), ...bandVals.flat().flat()]
    .filter((v) => v != null && Number.isFinite(v));
  if (!all.length) { el.innerHTML = `<p class="small muted">No data yet.</p>`; return; }
  const scale = o.scale ?? 1000;
  const [ylo, yhi, ticks] = niceScale(o.yMin ?? Math.min(...all), o.yMax ?? Math.max(...all), narrow ? 4 : 5, o.zero || stack.length > 0);
  const t0 = grid[0][1], t1 = Math.max(grid[grid.length - 1][1], t0 + HOUR);
  const X = (t) => m.l + ((t - t0) / (t1 - t0)) * (width - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - ylo) / (yhi - ylo)) * (height - m.t - m.b);
  const f1 = (n) => n.toFixed(1);

  let svg = `<g class="grid">${ticks.map((v) => `<line x1="${m.l}" x2="${width - m.r}" y1="${f1(Y(v))}" y2="${f1(Y(v))}"/>`).join("")}</g>`;
  const unitDigits = ticks.length > 1 && ticks[1] - ticks[0] < scale ? 1 : 0;
  svg += `<g>${ticks.map((v) => `<text x="${m.l - 6}" y="${f1(Y(v) + 4)}" text-anchor="end">${(v / scale).toFixed(unitDigits)}</text>`).join("")}</g>`;
  svg += `<text x="${m.l - 6}" y="10" text-anchor="end">${esc(o.unit || "GW")}</text>`;

  // Time axis: 3-hourly ticks for a day or so, otherwise one label per local day.
  const span = t1 - t0, xt = [];
  if (span <= 1.6 * DAY) {
    for (let t = Math.ceil((t0 - BRT_OFFSET_MS) / (3 * HOUR)) * 3 * HOUR + BRT_OFFSET_MS; t <= t1; t += 3 * HOUR) {
      xt.push(`<line class="gl" x1="${f1(X(t))}" x2="${f1(X(t))}" y1="${m.t}" y2="${height - m.b}"/><text x="${f1(X(t))}" y="${height - 8}" text-anchor="middle">${fmtTime(new Date(t))}</text>`);
    }
  } else if (span > 60 * DAY) {
    // Months: a line at each local month start, labelled "Jan ’26", thinned to fit.
    const fmtM = new Intl.DateTimeFormat("en-GB", { timeZone: "America/Sao_Paulo", month: "short", year: "2-digit" });
    const starts = [];
    const d0 = new Date(t0 - BRT_OFFSET_MS);
    for (let y = d0.getUTCFullYear(), mo = d0.getUTCMonth() + 1; ; mo++) {
      const t = Date.UTC(y, mo, 1) + BRT_OFFSET_MS;
      if (t > t1) break;
      starts.push(t);
    }
    const monthPx = (30 * DAY / (t1 - t0)) * (width - m.l - m.r);
    const every = Math.max(1, Math.ceil(52 / monthPx));
    starts.forEach((t, k) => {
      xt.push(`<line x1="${f1(X(t))}" x2="${f1(X(t))}" y1="${m.t}" y2="${height - m.b}"/>`);
      if (k % every === 0) xt.push(`<text x="${f1(X(t))}" y="${height - 8}" text-anchor="middle">${fmtM.format(new Date(t + 15 * DAY)).replace(" ", " ’")}</text>`);
    });
  } else {
    // Days. Label density follows the space a day gets: full ("Wed 23 Sept"), short ("Wed 23"),
    // or the day of the month every few days; gridlines only where they do not crowd.
    const dayPx = (DAY / (t1 - t0)) * (width - m.l - m.r);
    const style = dayPx >= 86 ? "full" : dayPx >= 50 ? "short" : "num";
    let every = style === "num" ? Math.max(1, Math.ceil(24 / dayPx)) : 1;
    if (every > 3) every = Math.max(1, Math.ceil(54 / dayPx));   // labels now carry the month
    const short = new Intl.DateTimeFormat("en-GB", { timeZone: "America/Sao_Paulo", weekday: "short", day: "numeric" });
    const num = new Intl.DateTimeFormat("en-GB", { timeZone: "America/Sao_Paulo", day: "numeric", month: every > 3 ? "short" : undefined });
    let k = 0;
    for (let t = Math.ceil((t0 - BRT_OFFSET_MS) / DAY) * DAY + BRT_OFFSET_MS; t <= t1; t += DAY, k++) {
      const end = Math.min(t + DAY, t1), mid = new Date((t + end) / 2);
      if (dayPx >= 12 || k % every === 0) xt.push(`<line x1="${f1(X(t))}" x2="${f1(X(t))}" y1="${m.t}" y2="${height - m.b}"/>`);
      if (style === "num") {
        if (k % every === 0) xt.push(`<text x="${f1(X(t))}" y="${height - 8}" text-anchor="middle">${num.format(new Date(t + DAY / 2))}</text>`);
        continue;
      }
      const text = style === "full" ? fmtDay(mid) : short.format(mid).replace(",", "");
      if (X(end) - X(t) > text.length * 5.5) xt.push(`<text x="${f1((X(t) + X(end)) / 2)}" y="${height - 8}" text-anchor="middle">${text}</text>`);
    }
  }
  svg += `<g class="grid">${xt.join("")}</g>`;

  const path = (vals) => {
    let s = "", open = false;
    vals.forEach((v, i) => {
      if (v == null || !Number.isFinite(v)) { open = false; return; }
      s += `${open ? "L" : "M"}${f1(X(grid[i][1]))},${f1(Y(v))}`; open = true;
    });
    return s;
  };
  const area = (upper, lower) => {
    const ok = grid.map((g, i) => i).filter((i) => upper[i] != null && lower[i] != null);
    if (!ok.length) return "";
    return `M${ok.map((i) => `${f1(X(grid[i][1]))},${f1(Y(upper[i]))}`).join("L")}L${ok.slice().reverse().map((i) => `${f1(X(grid[i][1]))},${f1(Y(lower[i]))}`).join("L")}Z`;
  };
  bands.forEach((b, k) => { svg += `<path class="${b.cls}" d="${area(bandVals[k].map((p) => (p ? p[1] : null)), bandVals[k].map((p) => (p ? p[0] : null)))}"/>`; });
  stack.forEach((s, k) => { svg += `<path class="area ${s.cls}" d="${area(stackVals[k].upper, stackVals[k].lower)}"/>`; });
  lines.forEach((l, k) => { svg += `<path class="line ${l.cls}" d="${path(lineVals[k])}"/>`; });
  if (o.now && o.now >= t0 && o.now <= t1) {
    svg += `<line class="now" x1="${f1(X(o.now))}" x2="${f1(X(o.now))}" y1="${m.t}" y2="${height - m.b}"/><text x="${f1(X(o.now) + 4)}" y="${m.t + 10}">now</text>`;
  }

  if (labels) {  // direct labels at the right end, nudged apart
    const items = [];
    stack.forEach((s, k) => { const i = lastIndex(stackVals[k].raw); if (i >= 0) items.push({ y: Y((stackVals[k].upper[i] + stackVals[k].lower[i]) / 2), text: s.name }); });
    lines.forEach((l, k) => { const i = lastIndex(lineVals[k]); if (i >= 0) items.push({ y: Y(lineVals[k][i]), text: l.name }); });
    items.sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) items[i].y = Math.max(items[i].y, items[i - 1].y + 13);
    const over = items.length ? items[items.length - 1].y - (height - m.b) : 0;
    if (over > 0) items.forEach((it) => { it.y -= over; });
    svg += items.map((it) => `<text class="dl" x="${width - m.r + 8}" y="${f1(it.y + 4)}">${esc(it.text)}</text>`).join("");
  }
  svg += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${height - m.b}" visibility="hidden"/>`;
  svg += `<rect class="hit" x="${m.l}" y="0" width="${width - m.l - m.r}" height="${height}" fill="transparent"/>`;
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" tabindex="0" role="img" aria-label="${esc(o.aria || "Chart")}. Use the left and right arrow keys to read values.">${svg}</svg>`;

  const rows = (i) => {
    const out = [];
    stack.forEach((s, k) => { const v = stackVals[k].raw[i]; if (v != null) out.push([s.name, v]); });
    lines.forEach((l, k) => { const v = lineVals[k][i]; if (v != null) out.push([l.name, v]); });
    bands.forEach((b, k) => { const v = bandVals[k][i]; if (v) out.push([b.name, v]); });
    return out;
  };
  const digits = o.digits ?? 2;
  const fmtV = (v) => (Array.isArray(v) ? `${(v[0] / scale).toFixed(digits - 1)} – ${(v[1] / scale).toFixed(digits - 1)}` : (v / scale).toFixed(digits));
  const step = grid.length > 1 ? grid[1][1] - grid[0][1] : HOUR;
  const when = (t) => (step >= DAY ? fmtDay(new Date(t)) : `${fmtDayTime(new Date(t))}${step < HOUR ? " (half hour)" : ""}`);
  const tipHtml = (i) => `<div class="t">${when(grid[i][1])} · ${esc(o.unit || "GW")}</div>${rows(i).map(([n, v]) => `<div class="r"><span>${esc(n)}</span><span>${fmtV(v)}</span></div>`).join("")}`;
  wire(el, width, grid.map((g) => X(g[1])), tipHtml, m, height);
}

function lastIndex(vals) { for (let i = vals.length - 1; i >= 0; i--) if (vals[i] != null) return i; return -1; }

// Pointer, touch and keyboard reading of a chart whose points sit at xs (SVG units).
function wire(el, width, xs, tipHtml, m, height) {
  const svg = el.querySelector("svg"), cross = svg.querySelector(".cross");
  let cur = -1;
  const place = (i, cx, cy) => {
    cur = i;
    cross.setAttribute("x1", xs[i]); cross.setAttribute("x2", xs[i]); cross.setAttribute("visibility", "visible");
    const box = svg.getBoundingClientRect(), scale = box.width / width;
    showTip(tipHtml(i), cx ?? box.left + xs[i] * scale, cy ?? box.top + (m.t + (height - m.t - m.b) / 3) * scale);
  };
  const nearest = (clientX) => {
    const box = svg.getBoundingClientRect(), px = (clientX - box.left) * (width / box.width);
    let lo = 0, hi = xs.length - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] < px) lo = mid; else hi = mid; }
    return Math.abs(xs[lo] - px) <= Math.abs(xs[hi] - px) ? lo : hi;
  };
  const hide = () => { cur = -1; cross.setAttribute("visibility", "hidden"); hideTip(); };
  svg.addEventListener("pointermove", (e) => place(nearest(e.clientX), e.clientX, e.clientY));
  svg.addEventListener("pointerdown", (e) => place(nearest(e.clientX), e.clientX, e.clientY));
  svg.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") hide(); });
  svg.addEventListener("focus", () => place(xs.length - 1));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (step) { e.preventDefault(); place(Math.min(xs.length - 1, Math.max(0, (cur < 0 ? xs.length - 1 : cur) + step))); }
    else if (e.key === "Home") { e.preventDefault(); place(0); }
    else if (e.key === "End") { e.preventDefault(); place(xs.length - 1); }
    else if (e.key === "Escape") hide();
  });
}

// A table view of a time chart, built only when opened.
export function tableTwin(opts, caption) {
  const d = document.createElement("details");
  d.className = "twin";
  d.innerHTML = `<summary>Show as table</summary>`;
  d.addEventListener("toggle", () => {
    if (!d.open || d.querySelector("table")) return;
    const cols = [...(opts.stack || []), ...(opts.lines || []), ...(opts.bands || [])];
    const stamps = [...new Set(cols.flatMap((c) => c.points.map((p) => p[0])))].sort();
    const maps = cols.map((c) => new Map(c.points.map((p) => [p[0], p])));
    const sc = opts.scale ?? 1000, dg = opts.digits ?? 2;
    const cell = (p, k) => (!p ? "–" : k >= (opts.stack || []).length + (opts.lines || []).length
      ? `${(p[1] / sc).toFixed(dg)} – ${(p[2] / sc).toFixed(dg)}` : p[1] == null ? "–" : (p[1] / sc).toFixed(dg));
    const daily = stamps.length > 1 && toDate(stamps[1]) - toDate(stamps[0]) >= DAY;
    d.insertAdjacentHTML("beforeend", `<div class="table-scroll"><table><caption class="small muted" style="text-align:left">${esc(caption)} (${esc(opts.unit || "GW")}${daily ? "" : ", Brasília time"})</caption><thead><tr><th>${daily ? "Day" : "Time"}</th>${cols.map((c) => `<th class="num">${esc(c.name)}</th>`).join("")}</tr></thead><tbody>${
      stamps.slice().reverse().map((s) => `<tr><td>${daily ? fmtDay(s) : fmtDayTime(s)}</td>${maps.map((mp, k) => `<td class="num">${cell(mp.get(s), k)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
  });
  return d;
}

// Lines over categories (e.g. error by days ahead). values are fractions, shown in percent.
export function categoryChart(el, { categories, series, aria, height }) {
  const draw = () => {
    const width = Math.max(el.clientWidth || 600, 280), narrow = width < 560;
    const h = height || (narrow ? 220 : 260);
    const m = { l: 44, r: 12, t: 14, b: 28 };
    const all = series.flatMap((s) => s.values).filter((v) => v != null);
    if (!all.length) { el.innerHTML = `<p class="small muted">No data yet.</p>`; return; }
    const [ylo, yhi, ticks] = niceScale(0, Math.max(...all), 4, true);
    const X = (i) => m.l + ((i + 0.5) / categories.length) * (width - m.l - m.r);
    const Y = (v) => m.t + (1 - (v - ylo) / (yhi - ylo)) * (h - m.t - m.b);
    let svg = `<g class="grid">${ticks.map((v) => `<line x1="${m.l}" x2="${width - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>`;
    svg += ticks.map((v) => `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${(v * 100).toFixed(v < 0.1 && ticks[1] < 0.02 ? 1 : 0)}%</text>`).join("");
    const every = Math.max(1, Math.ceil((categories.length * 46) / (width - m.l - m.r)));
    svg += categories.map((c, i) => (i % every ? "" : `<text x="${X(i)}" y="${h - 8}" text-anchor="middle">${esc(c)}</text>`)).join("");
    series.forEach((s) => {
      let d = "", open = false;
      s.values.forEach((v, i) => { if (v == null) { open = false; return; } d += `${open ? "L" : "M"}${X(i)},${Y(v)}`; open = true; });
      svg += `<path class="line" style="stroke:var(${VARS[s.cls]})${s.dash ? ";stroke-dasharray:6 4" : ""}" d="${d}"/>`;
      const last = lastIndex(s.values);
      svg += s.values.map((v, i) => (v == null ? "" : s.marker === "diamond"
        ? `<rect class="dotmark" x="${X(i) - 5}" y="${Y(v) - 5}" width="10" height="10" transform="rotate(45 ${X(i)} ${Y(v)})" style="fill:var(${VARS[s.cls]})"/>${i === last && s.label !== false ? `<text class="dl" x="${X(i) + 10}" y="${Y(v) + 4}">${esc(s.name)}</text>` : ""}`
        : `<circle class="dotmark" cx="${X(i)}" cy="${Y(v)}" r="${categories.length > 12 ? 3 : 4}" style="fill:var(${VARS[s.cls]})"/>`)).join("");
    });
    svg += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${h - m.b}" visibility="hidden"/>`;
    el.innerHTML = `<svg class="chart" viewBox="0 0 ${width} ${h}" width="${width}" height="${h}" tabindex="0" role="img" aria-label="${esc(aria || "Chart")}. Use the arrow keys to read values.">${svg}</svg>`;
    const tipHtml = (i) => `<div class="t">${esc(categories[i])}</div>${series.filter((s) => s.values[i] != null).map((s) => `<div class="r"><span>${esc(s.name)}</span><span>${(s.values[i] * 100).toFixed(2)}%</span></div>`).join("")}`;
    wire(el, width, categories.map((c, i) => X(i)), tipHtml, m, h);
  };
  observe(el, draw);
  draw();
}

export const modelLegend = (models) => legend(models.map(([key, name]) => ({ name, cls: `m-${key}`, kind: key === "seasonal_naive" ? "dash" : key === "ons_programme" ? "box" : "line" })));
export { fmtTime };

// Chart options for "how the forecast for one day changed": one line per issue, older lighter;
// the newest issue's 80% band; the actual values; the operator's programme when given.
// issues: [{label, points:[[t, q10, q50, q90]]}] oldest first.
export function vintageOpts(issues, actual, programme, aria) {
  const n = issues.length;
  const lines = issues.map((iss, i) => ({ name: iss.label, cls: `e-seq${7 - (n - 1 - i)}${i === n - 1 ? " e-seq-latest" : ""}`, points: iss.points.map((p) => [p[0], p[2]]) }));
  if (programme?.length) lines.push({ name: "Operator's programme", cls: "e-programme", points: programme });
  if (actual?.length) lines.push({ name: "Actual", cls: "e-actual", points: actual });
  const latest = issues[n - 1];
  return { lines, bands: latest ? [{ name: `80% interval (${latest.label})`, cls: "band80", points: latest.points.map((p) => [p[0], p[1], p[3]]) }] : [], aria };
}

export function vintageLegend(issues, withProgramme, withActual) {
  const n = issues.length;
  return legend([
    ...issues.map((iss, i) => ({ name: iss.label, cls: `e-seq${7 - (n - 1 - i)}` })),
    ...(withProgramme ? [{ name: "Operator's programme", cls: "e-programme", kind: "dash" }] : []),
    ...(withActual ? [{ name: "Actual", cls: "e-actual" }] : []),
    ...(n ? [{ name: "80% interval, latest", cls: "band80", kind: "box" }] : []),
  ]);
}

// Stacked columns over categories (e.g. months). stack: [{name, cls, values}]; values in `unit`.
export function barChart(el, { categories, stack, unit, aria, digits = 0, height }) {
  const draw = () => {
    const width = Math.max(el.clientWidth || 600, 280), narrow = width < 560;
    const h = height || (narrow ? 220 : 260);
    const m = { l: 48, r: 10, t: 22, b: 28 };
    const totals = categories.map((c, i) => stack.reduce((a, s) => a + (s.values[i] || 0), 0));
    if (!totals.some((v) => v > 0)) { el.innerHTML = `<p class="small muted">No data yet.</p>`; return; }
    const [, yhi, ticks] = niceScale(0, Math.max(...totals), 4, true);
    const band = (width - m.l - m.r) / categories.length, bw = Math.max(4, Math.min(38, band * 0.7));
    const X = (i) => m.l + band * (i + 0.5);
    const Y = (v) => m.t + (1 - v / yhi) * (h - m.t - m.b);
    let svg = `<g class="grid">${ticks.map((v) => `<line x1="${m.l}" x2="${width - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>`;
    svg += ticks.map((v) => `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toLocaleString("en-GB")}</text>`).join("");
    svg += `<text x="${m.l - 6}" y="10" text-anchor="end">${esc(unit)}</text>`;
    const every = Math.max(1, Math.ceil((categories.length * 44) / (width - m.l - m.r)));
    svg += categories.map((c, i) => (i % every ? "" : `<text x="${X(i)}" y="${h - 8}" text-anchor="middle">${esc(c)}</text>`)).join("");
    categories.forEach((c, i) => {
      let base = 0;
      stack.forEach((s) => {
        const v = s.values[i] || 0;
        if (v <= 0) return;
        const y0 = Y(base), y1 = Y(base + v);
        svg += `<rect class="${s.cls}" x="${X(i) - bw / 2}" y="${y1}" width="${bw}" height="${Math.max(0, y0 - y1 - 1.5)}" rx="2" style="stroke:none"/>`;
        base += v;
      });
    });
    svg += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${h - m.b}" visibility="hidden"/>`;
    el.innerHTML = `<svg class="chart" viewBox="0 0 ${width} ${h}" width="${width}" height="${h}" tabindex="0" role="img" aria-label="${esc(aria || "Chart")}. Use the arrow keys to read values.">${svg}</svg>`;
    const tipHtml = (i) => `<div class="t">${esc(categories[i])} · ${esc(unit)}</div>${stack.map((s) => `<div class="r"><span>${esc(s.name)}</span><span>${(s.values[i] || 0).toLocaleString("en-GB", { maximumFractionDigits: digits })}</span></div>`).join("")}<div class="r"><span><b>Total</b></span><span><b>${totals[i].toLocaleString("en-GB", { maximumFractionDigits: digits })}</b></span></div>`;
    wire(el, width, categories.map((c, i) => X(i)), tipHtml, m, h);
  };
  observe(el, draw);
  draw();
}

// Schematic of the four subsystems with the flow on each link: arrow width follows the flow,
// direction follows its sign. pairs: [{a, b, mw, programmed_mw}] with mw > 0 meaning a to b.
const LABELS = { "N-NE": [270, 44, "middle"], "N-SE": [196, 150, "end"], "NE-SE": [346, 150, "start"], "SE-S": [294, 284, "start"] };

export function flowMap(el, pairs, names) {
  const pos = { N: [150, 70], NE: [390, 70], SE: [270, 220], S: [270, 355] };
  const max = Math.max(1, ...pairs.map((p) => Math.abs(p.mw)));
  let svg = "";
  pairs.forEach((p) => {
    const [from, to] = p.mw >= 0 ? [p.a, p.b] : [p.b, p.a];
    const [x1, y1] = pos[from], [x2, y2] = pos[to];
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
    const sx = x1 + ux * 46, sy = y1 + uy * 30, ex = x2 - ux * 50, ey = y2 - uy * 34;
    const w = 2 + 10 * (Math.abs(p.mw) / max);
    const mx = (sx + ex) / 2, my = (sy + ey) / 2, nx = -uy, ny = ux;   // midpoint and normal
    svg += `<line x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}" stroke="var(--accent)" stroke-width="${w.toFixed(1)}" stroke-linecap="round" marker-end="url(#arrow)" opacity="0.85"/>`;
    const prog = p.programmed_mw == null ? "" : `programmed ${(Math.abs(p.programmed_mw) / 1000).toFixed(1)}${Math.sign(p.programmed_mw || 0) !== Math.sign(p.mw || 0) ? " the other way" : ""}`;
    // Hand-placed labels: the schematic is fixed, so each link has a clear spot beside it.
    const [lx, ty, anchor] = LABELS[`${p.a}-${p.b}`] || [mx + nx * 20, my + ny * 20, "middle"];
    svg += `<text x="${lx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}" class="dl">${(Math.abs(p.mw) / 1000).toFixed(1)} GW</text>`;
    if (prog) svg += `<text x="${lx.toFixed(1)}" y="${(ty + 13).toFixed(1)}" text-anchor="${anchor}">${esc(prog)}</text>`;
  });
  Object.entries(pos).forEach(([k, [x, y]]) => {
    svg += `<rect x="${x - 44}" y="${y - 22}" width="88" height="44" rx="10" fill="var(--surface-2)" stroke="var(--axis)"/><text x="${x}" y="${y - 3}" text-anchor="middle" class="dl">${esc(k)}</text><text x="${x}" y="${y + 12}" text-anchor="middle">${esc(names[k] || "")}</text>`;
  });
  el.innerHTML = `<svg class="chart" viewBox="0 0 540 400" role="img" aria-label="Flows between subsystems: ${esc(pairs.map((p) => `${p.mw >= 0 ? p.a : p.b} to ${p.mw >= 0 ? p.b : p.a} ${(Math.abs(p.mw) / 1000).toFixed(1)} GW`).join(", "))}" style="max-width:560px;margin:0 auto">
    <defs><marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="var(--accent)"/></marker></defs>${svg}</svg>`;
}

// Signed columns (e.g. net flow by day or month): positive values in the "in" colour above zero,
// negative in the "out" colour below; partial[i] fades a column whose figure is still arriving.
// values in raw units, shown divided by `scale` with `digits` decimals.
export function signedBars(el, { categories, values, partial = [], unit, scale = 1, digits = 1, aria, height, notes = [] }) {
  const draw = () => {
    const width = Math.max(el.clientWidth || 600, 280), narrow = width < 560;
    const h = height || (narrow ? 220 : 260);
    const m = { l: 48, r: 10, t: 22, b: 28 };
    const vals = values.map((v) => (v == null ? null : v / scale));
    const ok = vals.filter((v) => v != null);
    if (!ok.length) { el.innerHTML = `<p class="small muted">No data yet.</p>`; return; }
    const [ylo, yhi, ticks] = niceScale(Math.min(0, ...ok), Math.max(0, ...ok), 4, true);
    const band = (width - m.l - m.r) / categories.length, bw = Math.max(2, Math.min(30, band * 0.72));
    const X = (i) => m.l + band * (i + 0.5);
    const Y = (v) => m.t + (1 - (v - ylo) / (yhi - ylo)) * (h - m.t - m.b);
    let svg = `<g class="grid">${ticks.map((v) => `<line x1="${m.l}" x2="${width - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>`;
    svg += ticks.map((v) => `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toLocaleString("en-GB")}</text>`).join("");
    svg += `<text x="${m.l - 6}" y="10" text-anchor="end">${esc(unit)}</text>`;
    const every = Math.max(1, Math.ceil((categories.length * 46) / (width - m.l - m.r)));
    svg += categories.map((c, i) => (i % every ? "" : `<text x="${X(i)}" y="${h - 8}" text-anchor="middle">${esc(c)}</text>`)).join("");
    vals.forEach((v, i) => {
      if (v == null || v === 0) return;
      const y0 = Y(0), y1 = Y(v), top = Math.min(y0, y1), hh = Math.max(1, Math.abs(y1 - y0));
      svg += `<rect class="${v > 0 ? "b-in" : "b-out"}${partial[i] ? " partial" : ""}" x="${X(i) - bw / 2}" y="${top}" width="${bw}" height="${hh}" rx="2"/>`;
    });
    svg += `<line class="zero" x1="${m.l}" x2="${width - m.r}" y1="${Y(0)}" y2="${Y(0)}"/>`;
    svg += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${h - m.b}" visibility="hidden"/>`;
    el.innerHTML = `<svg class="chart" viewBox="0 0 ${width} ${h}" width="${width}" height="${h}" tabindex="0" role="img" aria-label="${esc(aria || "Chart")}. Use the arrow keys to read values.">${svg}</svg>`;
    const tipHtml = (i) => `<div class="t">${esc(categories[i])} · ${esc(unit)}</div><div class="r"><span>${vals[i] == null ? "" : vals[i] >= 0 ? "In" : "Out"}</span><span>${vals[i] == null ? "–" : vals[i].toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits })}</span></div>${notes[i] ? `<div class="small muted">${esc(notes[i])}</div>` : ""}`;
    wire(el, width, categories.map((c, i) => X(i)), tipHtml, m, h);
  };
  observe(el, draw);
  draw();
}

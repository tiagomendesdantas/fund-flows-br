// Overview: this month and last month's net flow, net assets, how much of the latest days is in,
// daily net flow with the days still arriving faded, and the split by category.
import { fill, getJSON, skeleton } from "../api.js";
import { legend, signedBars } from "../chart.js";
import { CATEGORY_SEGMENTS, bn, dateOnly, dayOnly, esc, monthOnly, pct, sbn, segmentName, spct, tn } from "../fmt.js";
import { tile } from "../ui.js";

export default function overview(main) {
  main.innerHTML = `
    <h1 class="view">Overview</h1>
    <p class="sub">Money in and out of Brazil's investment funds, from CVM's daily fund report. Funds that invest in other funds are left out, so each flow is counted once. R$ billion unless stated.</p>
    <div class="tiles four" id="tiles">${Array.from({ length: 4 }, () => `<div class="tile">${skeleton("tile")}</div>`).join("")}</div>
    <div class="grid">
      <section class="card span-12" aria-labelledby="h-daily">
        <div class="card-head"><h2 id="h-daily">Net flow by day</h2><span class="meta" id="daily-meta"></span></div>
        <div id="daily-legend"></div><div class="chart-box" id="daily-chart">${skeleton()}</div>
        <p class="note">Subscriptions minus redemptions, all funds without funds of funds. Funds mostly report the business day after: a day appears in CVM's file two business days later with 84–94% of funds in, and is about complete after five. Faded columns are days still arriving; their figures will grow.</p>
        <details class="twin"><summary>Table</summary><div id="daily-table"></div></details>
      </section>
      <section class="card span-12" aria-labelledby="h-cat">
        <div class="card-head"><h2 id="h-cat">By category</h2><span class="meta" id="cat-meta"></span></div>
        <div id="cats">${skeleton("text")}</div>
      </section>
      <section class="card span-12" aria-labelledby="h-next">
        <div class="card-head"><h2 id="h-next">Next on this page</h2></div>
        <p class="small">Each morning, an estimate of every incomplete day's final total, with a range, made before the late reports arrive, and a public record of how each estimate compared with CVM's complete figure. Collection of every version of CVM's file began on 1 October 2026; the method and its test are on the <a href="/method" data-link>Method</a> page.</p>
      </section>
    </div>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#tiles"), async () => {
    const o = await getJSON("/api/overview", "overview");
    const seg = (part, s) => (part.segments || []).find((r) => r.segment === s);
    const now = seg(o.this_month, "direct"), last = seg(o.last_month, "direct");
    const lag2 = (o.completeness || []).find((d) => d.lag === 2);
    const t = [];
    t.push(now ? tile(`Net flow, ${monthOnly(o.this_month.month)} so far`, sbn(now.net), "R$ bn",
      `${now.days} business day${now.days === 1 ? "" : "s"} through ${dayOnly(now.through)}${o.this_month.partial_days ? `; <b>${o.this_month.partial_days}</b> still arriving` : ""}`)
      : tile(`Net flow, ${monthOnly(o.this_month.month)} so far`, "–", "", "no day of this month is mostly reported yet"));
    t.push(last ? tile(`Net flow, ${monthOnly(o.last_month.month)}`, sbn(last.net), "R$ bn",
      `in ${bn(last.captc)}, out ${bn(last.resg)}${o.last_month.partial_days ? `<br><b>${o.last_month.partial_days}</b> days still arriving` : "<br>all days about complete"}`)
      : tile(`Net flow, ${monthOnly(o.last_month.month)}`, "–", "", "not available"));
    t.push(o.assets ? tile("Net assets", tn(o.assets.pl), "R$ tn", `on ${dateOnly(o.assets.dt)}, without funds of funds<br>${(o.assets.cotst / 1e6).toLocaleString("en-GB", { maximumFractionDigits: 1 })} million quota holdings`)
      : tile("Net assets", "–", "", "not available"));
    t.push(lag2 ? tile("Reported so far", pct(lag2.share, 0), "", `of fund classes for ${dayOnly(lag2.dt)}, against the usual ${Math.round(lag2.usual).toLocaleString("en-GB")}<br>CVM file of ${dayOnly(o.file_day)}`)
      : tile("Reported so far", "–", "", "no file read yet"));
    $("#tiles").innerHTML = t.join("");

    const days = o.daily || [];
    $("#daily-meta").textContent = days.length ? `${dateOnly(days[0].dt)} – ${dateOnly(days[days.length - 1].dt)}` : "";
    $("#daily-legend").innerHTML = legend([{ name: "Net inflow", cls: "b-in", kind: "box" }, { name: "Net outflow", cls: "b-out", kind: "box" }]) + `<p class="small muted" style="margin:0 0 4px">Faded with a dashed outline: reports still arriving.</p>`;
    signedBars($("#daily-chart"), {
      categories: days.map((d) => dayOnly(d.dt)), values: days.map((d) => d.net), partial: days.map((d) => d.lag <= 5),
      notes: days.map((d) => (d.lag <= 5 ? `still arriving (${d.lag} business days after)` : "")),
      unit: "R$ bn", scale: 1e9, digits: 1, aria: "Net flow by day, without funds of funds, in R$ billion",
    });
    $("#daily-table").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Day</th><th class="num">Subscriptions</th><th class="num">Redemptions</th><th class="num">Net</th><th>State</th></tr></thead><tbody>${
      days.slice().reverse().map((d) => `<tr><td>${dayOnly(d.dt)}</td><td class="num">${bn(d.captc)}</td><td class="num">${bn(d.resg)}</td><td class="num">${sbn(d.net)}</td><td class="small muted">${d.lag <= 5 ? "still arriving" : ""}</td></tr>`).join("")
    }</tbody></table></div>`;

    const cats = CATEGORY_SEGMENTS.map(([s]) => [s, seg(o.this_month, s), seg(o.last_month, s)]).filter(([, a, b]) => a || b);
    $("#cat-meta").textContent = `${monthOnly(o.this_month.month)} so far and ${monthOnly(o.last_month.month)}`;
    const cell = (r, f) => (!r ? "–" : r.shown ? f(r) : `<span class="muted">hidden</span>`);
    $("#cats").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Category</th><th class="num">Net, ${esc(monthOnly(o.this_month.month))}</th><th class="num">Net, ${esc(monthOnly(o.last_month.month))}</th><th class="num">as % of assets</th><th class="num">Net assets, R$ tn</th></tr></thead><tbody>${
      cats.map(([s, a, b]) => `<tr><td>${esc(segmentName(s))}</td><td class="num">${cell(a, (r) => sbn(r.net))}</td><td class="num">${cell(b, (r) => sbn(r.net))}</td><td class="num">${s.endsWith("Unclassified") ? "–" : cell(b, (r) => spct(r.net / r.pl_end))}</td><td class="num">${cell(b, (r) => tn(r.pl_end))}</td></tr>`).join("")
    }</tbody></table></div><p class="note">CVM's classification of each fund class (Renda Fixa, Multimercado, Ações, Cambial; FMP-FGTS are funds of the workers' severance fund). Unclassified: classes in neither register, mostly funds being wound up, with redemptions and almost no assets left; in August 2026 about a quarter of their large redemptions reappeared the same day as subscriptions of nearly the same amount in other funds, so this row overstates money leaving (the total above nets those moves out). A month's figure is hidden when fewer than 10 funds reported or one fund made more than half of its flow, so that no fund's own figures can be read off a total.</p>`;
  });
  render();
  return { refresh: render };
}

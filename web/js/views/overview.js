// Overview: the headline sentence, four key figures, net flow by day, the split by category.
import { fill, getJSON, skeleton } from "../api.js";
import { legend, signedBars } from "../chart.js";
import { CATEGORY_SEGMENTS, bn, dateOnly, dayOnly, esc, monthOnly, pct, sbn, segmentName, spct, tn } from "../fmt.js";
import { figure } from "../ui.js";

export default function overview(main) {
  main.innerHTML = `
    <h1 class="view">Overview</h1>
    <p class="headline" id="headline">${skeleton("text")}</p>
    <div class="figures" id="figures">${Array.from({ length: 4 }, () => `<div class="figure">${skeleton("text")}</div>`).join("")}</div>
    <section class="sec" aria-labelledby="h-daily">
      <div class="sec-head"><h2 id="h-daily">Net flow by day</h2><span class="meta" id="daily-meta"></span></div>
      <p class="subtitle">Subscriptions minus redemptions, R$ bn, funds of funds excluded.${legend([{ name: "Net inflow", cls: "b-in", kind: "box" }, { name: "Net outflow", cls: "b-out", kind: "box" }, { name: "Still arriving", cls: "b-in", kind: "hatch" }])}</p>
      <div class="chart-box" id="daily-chart">${skeleton()}</div>
      <details class="twin"><summary>Table</summary><div id="daily-table"></div></details>
      <ol class="notes"><li>Funds mostly report on the business day after. A day appears in CVM's file two business days later with 84–94% of funds in, and is about complete after five; hatched days are still arriving and their figures will grow.</li></ol>
      <p class="source" id="daily-source"></p>
    </section>
    <section class="sec" aria-labelledby="h-cat">
      <div class="sec-head"><h2 id="h-cat">By category</h2><span class="meta" id="cat-meta"></span></div>
      <p class="subtitle">Net flow, R$ bn, by CVM classification of each fund class; funds of funds excluded.</p>
      <div id="cats">${skeleton("text")}</div>
      <ol class="notes">
        <li>FMP-FGTS are funds of the workers' severance fund. Unclassified: classes in neither of CVM's registers, mostly funds being wound up; in August 2026 about a quarter of their large redemptions reappeared the same day as subscriptions of nearly the same amount in other funds, so this row overstates money leaving (the industry total nets those moves out).</li>
        <li>A month is shown as "–" when fewer than 10 funds reported or one fund made more than half of its flow, so that no fund's own figures can be read off a total.</li>
      </ol>
    </section>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#figures"), async () => {
    const o = await getJSON("/api/overview", "overview");
    const seg = (part, s) => (part.segments || []).find((r) => r.segment === s);
    const now = seg(o.this_month, "direct"), last = seg(o.last_month, "direct");
    const lag2 = (o.completeness || []).find((d) => d.lag === 2);
    $("#headline").textContent = o.headline;
    const t = [];
    t.push(now ? figure(`Net flow, ${monthOnly(o.this_month.month)} so far`, sbn(now.net), "R$ bn",
      `${now.days} business day${now.days === 1 ? "" : "s"} through ${dayOnly(now.through)}${o.this_month.partial_days ? `; <b>${o.this_month.partial_days}</b> still arriving` : ""}`)
      : figure(`Net flow, ${monthOnly(o.this_month.month)}`, "–", "", "no day of the month mostly reported yet"));
    t.push(last ? figure(`Net flow, ${monthOnly(o.last_month.month)}`, sbn(last.net), "R$ bn",
      `in ${bn(last.captc)}, out ${bn(last.resg)}${o.last_month.partial_days ? `; <b>${o.last_month.partial_days}</b> days still arriving` : "; all days about complete"}`)
      : figure(`Net flow, ${monthOnly(o.last_month.month)}`, "–", "", "not available"));
    t.push(o.assets ? figure("Net assets", tn(o.assets.pl), "R$ tn", `${dateOnly(o.assets.dt)}, funds of funds excluded; ${(o.assets.cotst / 1e6).toLocaleString("en-GB", { maximumFractionDigits: 1 })} million quota holdings`)
      : figure("Net assets", "–", "", "not available"));
    t.push(lag2 ? figure("Reported so far", pct(lag2.share, 0), "", `of fund classes for ${dayOnly(lag2.dt)}, against the usual ${Math.round(lag2.usual).toLocaleString("en-GB")}`)
      : figure("Reported so far", "–", "", "no file read yet"));
    $("#figures").innerHTML = t.join("");

    const days = o.daily || [];
    $("#daily-meta").textContent = days.length ? `${dateOnly(days[0].dt)} – ${dateOnly(days[days.length - 1].dt)}` : "";
    signedBars($("#daily-chart"), {
      categories: days.map((d) => dayOnly(d.dt)), values: days.map((d) => d.net), partial: days.map((d) => d.lag <= 5),
      notes: days.map((d) => (d.lag <= 5 ? `still arriving, ${d.lag} business day${d.lag === 1 ? "" : "s"} after` : "")),
      unit: "R$ bn", scale: 1e9, digits: 1, aria: "Net flow by day, funds of funds excluded, in R$ billion",
    });
    $("#daily-table").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Day</th><th class="num">Subscriptions</th><th class="num">Redemptions</th><th class="num">Net</th><th></th></tr></thead><tbody>${
      days.slice().reverse().map((d) => `<tr><td>${dayOnly(d.dt)}</td><td class="num">${bn(d.captc)}</td><td class="num">${bn(d.resg)}</td><td class="num">${sbn(d.net)}</td><td>${d.lag <= 5 ? '<span class="partial">still arriving</span>' : ""}</td></tr>`).join("")
    }</tbody></table></div>`;
    $("#daily-source").textContent = `Source: CVM daily fund report, file of ${dayOnly(o.file_day)}.`;

    const cats = CATEGORY_SEGMENTS.map(([s]) => [s, seg(o.this_month, s), seg(o.last_month, s)]).filter(([, a, b]) => a || b);
    $("#cat-meta").textContent = `${monthOnly(o.this_month.month)} so far and ${monthOnly(o.last_month.month)}`;
    const cell = (r, f) => (!r ? "–" : r.shown ? f(r) : "–<sup>2</sup>");
    $("#cats").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Category<sup>1</sup></th><th class="num">${esc(monthOnly(o.this_month.month))}</th><th class="num">${esc(monthOnly(o.last_month.month))}</th><th class="num">% of assets</th><th class="num">Net assets, R$ tn</th></tr></thead><tbody>${
      cats.map(([s, a, b]) => `<tr><td>${esc(segmentName(s))}</td><td class="num">${cell(a, (r) => sbn(r.net))}</td><td class="num">${cell(b, (r) => sbn(r.net))}</td><td class="num">${s.endsWith("Unclassified") ? "–" : cell(b, (r) => spct(r.net / r.pl_end))}</td><td class="num">${cell(b, (r) => tn(r.pl_end))}</td></tr>`).join("")
    }</tbody></table></div>`;
  });
  render();
  return { refresh: render };
}

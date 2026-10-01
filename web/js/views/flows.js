// Flows: net flow by month, net assets, and daily subscriptions and redemptions for one group.
import { fill, getJSON, skeleton } from "../api.js";
import { legend, signedBars, tableTwin, timeChart } from "../chart.js";
import { SEGMENTS, bn, dayAt, dateOnly, monthOnly, sbn, segmentName, spct, tn } from "../fmt.js";
import { segmented } from "../ui.js";

const RANGES = [["1y", "1 year"], ["3y", "3 years"], ["all", "Since 2021"]];

export default function flows(main, { readState, writeState }) {
  const state = readState([["segment", SEGMENTS.map((s) => s[0]), "direct"], ["range", RANGES.map((r) => r[0]), "1y"]]);
  main.innerHTML = `
    <h1 class="view">Flows</h1>
    <div class="controls">
      <div class="seg" id="seg" aria-label="Funds"></div>
      <div class="seg" id="range" aria-label="Period"></div>
    </div>
    <section class="sec" aria-labelledby="h-month">
      <div class="sec-head"><h2 id="h-month">Net flow by month</h2><span class="meta" id="month-meta"></span></div>
      <p class="subtitle">Subscriptions minus redemptions, R$ bn.${legend([{ name: "Net inflow", cls: "b-in", kind: "box" }, { name: "Net outflow", cls: "b-out", kind: "box" }, { name: "Days still arriving", cls: "b-in", kind: "hatch" }])}</p>
      <div class="chart-box" id="month-chart">${skeleton()}</div>
      <details class="twin"><summary>Table</summary><div id="month-table"></div></details>
      <ol class="notes" id="month-notes"></ol>
    </section>
    <div class="two">
      <section class="sec" aria-labelledby="h-pl">
        <div class="sec-head"><h2 id="h-pl">Net assets</h2><span class="meta">R$ tn</span></div>
        <p class="subtitle">On days about complete; the latest five business days are left out.</p>
        <div class="chart-box" id="pl-chart">${skeleton()}</div><div id="pl-twin"></div>
      </section>
      <section class="sec" aria-labelledby="h-gross">
        <div class="sec-head"><h2 id="h-gross">Subscriptions and redemptions</h2><span class="meta">R$ bn, last three months</span></div>
        <p class="subtitle">${legend([{ name: "Subscriptions", cls: "e-in" }, { name: "Redemptions", cls: "e-out" }])}</p>
        <div class="chart-box" id="gross-chart">${skeleton()}</div><div id="gross-twin"></div>
      </section>
    </div>
    <p class="source" id="flows-source"></p>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#month-chart"), async () => {
    const f = await getJSON(`/api/flows?segment=${encodeURIComponent(state.segment)}`, "flows");
    const name = segmentName(state.segment);
    const keep = state.range === "all" ? Infinity : state.range === "3y" ? 36 : 12;
    const months = f.months.slice(-keep);
    $("#month-meta").textContent = name;
    signedBars($("#month-chart"), {
      categories: months.map((m) => monthOnly(m.month)), values: months.map((m) => m.net), partial: months.map((m) => m.partial),
      notes: months.map((m) => (m.partial ? "some days still arriving" : "")), flag: "days still arriving",
      unit: "R$ bn", scale: 1e9, digits: 1, aria: `Net flow by month, ${name}, in R$ billion`,
    });
    $("#month-table").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Month</th><th class="num">Subscriptions</th><th class="num">Redemptions</th><th class="num">Net</th><th class="num">% of assets</th><th class="num">Net assets, R$ tn</th></tr></thead><tbody>${
      months.slice().reverse().map((m) => `<tr><td>${monthOnly(m.month)}${m.partial ? ' <span class="partial">partial</span>' : ""}</td><td class="num">${bn(m.captc)}</td><td class="num">${bn(m.resg)}</td><td class="num">${sbn(m.net)}</td><td class="num">${spct(m.net / m.pl_end)}</td><td class="num">${tn(m.pl_end)}</td></tr>`).join("")
    }</tbody></table></div>`;
    $("#month-notes").innerHTML = [
      state.segment === "all" ? "<li>Funds of funds included: money a fund of funds places in another fund is counted in both.</li>" : state.segment === "direct" ? "<li>Funds of funds excluded, so each flow is counted once.</li>" : "",
      f.hidden_days ? `<li>${f.hidden_days} days hidden: fewer than 10 funds reported or one fund made more than half of the flow.</li>` : "",
    ].join("");

    const first = months.length ? `${months[0].month}-01` : "";
    const daily = f.daily.filter((r) => r[0] >= first);
    const plOpts = { lines: [{ name: "Net assets", cls: "e-assets", points: daily.filter((r) => r[5] > 5).map((r) => [dayAt(r[0]), r[3]]) }],
      unit: "R$ tn", scale: 1e12, digits: 2, labels: false, aria: `Net assets, ${name}, in R$ trillion` };
    timeChart($("#pl-chart"), plOpts);
    $("#pl-twin").replaceChildren(tableTwin(plOpts, `Net assets, ${name}`));

    const recent = f.daily.slice(-63);
    const grossOpts = { lines: [
      { name: "Subscriptions", cls: "e-in", points: recent.map((r) => [dayAt(r[0]), r[1]]) },
      { name: "Redemptions", cls: "e-out", points: recent.map((r) => [dayAt(r[0]), r[2]]) }],
    unit: "R$ bn", scale: 1e9, digits: 1, zero: true, labels: false, aria: `Subscriptions and redemptions by day, ${name}, in R$ billion` };
    timeChart($("#gross-chart"), grossOpts);
    $("#gross-twin").replaceChildren(tableTwin(grossOpts, `Subscriptions and redemptions, ${name}`));
    $("#flows-source").textContent = `Source: CVM daily fund report, file of ${dateOnly(f.file_day)}; data from January 2021.`;
  });

  segmented($("#seg"), "Funds", SEGMENTS.map(([v, l]) => [v, l.replace("All funds, without funds of funds", "All funds").replace("All funds, with funds of funds (counted twice)", "With funds of funds")]), state.segment, (v) => { state.segment = v; writeState(state); render(); });
  segmented($("#range"), "Period", RANGES, state.range, (v) => { state.range = v; writeState(state); render(); });
  render();
  return { refresh: render };
}

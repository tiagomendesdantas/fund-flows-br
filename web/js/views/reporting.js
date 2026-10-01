// Reporting: how complete each recent day is, when reports usually arrive, and what each new
// version of CVM's file added and changed.
import { fill, getJSON, skeleton } from "../api.js";
import { dayOnly, fmtDayTime, monthOnly, pct, sbn } from "../fmt.js";

const ym = (m) => monthOnly(`${m.slice(0, 4)}-${m.slice(4)}`);

export default function reporting(main) {
  main.innerHTML = `
    <h1 class="view">Reporting</h1>
    <p class="headline">Funds send CVM a daily report, mostly on the business day after. CVM rewrites its file every morning with what has arrived, resubmissions included.</p>
    <div class="two">
      <section class="sec" aria-labelledby="h-now">
        <div class="sec-head"><h2 id="h-now">The latest days</h2><span class="meta" id="now-meta"></span></div>
        <p class="subtitle">Fund classes reported, against the usual count.<sup>1</sup></p>
        <div id="now">${skeleton("text")}</div>
      </section>
      <section class="sec" aria-labelledby="h-usual">
        <div class="sec-head"><h2 id="h-usual">When reports arrive</h2><span class="meta" id="usual-meta"></span></div>
        <p class="subtitle">Share in by business days after the day reported; average, with the range across months.<sup>2</sup></p>
        <div id="usual">${skeleton("text")}</div>
      </section>
    </div>
    <section class="sec" aria-labelledby="h-files">
      <div class="sec-head"><h2 id="h-files">What each file added and changed</h2><span class="meta">daily report, latest versions</span></div>
      <p class="subtitle">Fund-days added and changed against the previous version; changes in R$ bn, summed over the month.<sup>3</sup></p>
      <div id="files">${skeleton("text")}</div>
    </section>
    <ol class="notes">
      <li>The usual count is the median of the about-complete days among the previous 30. Fund classes open and close, so a complete day can sit slightly above or below it.</li>
      <li>From CVM's delivery log: the first delivery of each fund-day and the morning file it first appeared in. Funds that report late hold about 7% of net assets and move more, relative to their size, than funds on time.</li>
      <li>A changed fund-day is one whose figures differ from the previous version. Every earlier version is kept.</li>
    </ol>
    <p class="source" id="rep-source"></p>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#now"), async () => {
    const r = await getJSON("/api/reporting", "reporting");
    $("#now-meta").textContent = r.file_day ? `file of ${dayOnly(r.file_day)}` : "";
    $("#now").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Day</th><th class="num">Days after</th><th class="num">Classes in</th><th>Share of the usual</th></tr></thead><tbody>${
      r.completeness.map((d) => `<tr><td class="nowrap">${dayOnly(d.dt)}</td><td class="num">${d.lag}</td><td class="num">${d.n.toLocaleString("en-GB")}</td><td><div style="display:flex;align-items:center;gap:8px"><div class="bar-meter" style="flex:1"><span style="width:${Math.round((d.share || 0) * 100)}%"></span></div><span class="num small" style="min-width:46px;text-align:right">${pct(d.share, 1)}</span></div></td></tr>`).join("")
    }</tbody></table></div>`;
    $("#files").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Written by CVM</th><th>Month</th><th class="num">Added</th><th class="num">Changed</th><th class="num">Subscriptions</th><th class="num">Redemptions</th></tr></thead><tbody>${
      r.releases.map((x) => `<tr><td class="nowrap">${fmtDayTime(x.written)}</td><td>${ym(x.month)}</td>${x.bootstrap
        ? `<td class="num">${x.new.toLocaleString("en-GB")}</td><td colspan="3" class="muted">first read of a month already published: a starting point, not new reports</td>`
        : `<td class="num">${x.new.toLocaleString("en-GB")}</td><td class="num">${x.changed.toLocaleString("en-GB")}</td><td class="num">${sbn(x.d_captc, 2)}</td><td class="num">${sbn(x.d_resg, 2)}</td>`}</tr>`).join("")
    }</tbody></table></div>`;
    $("#rep-source").textContent = `Source: CVM daily fund report and delivery log, file of ${dayOnly(r.file_day)}.`;
  });

  const usual = () => fill($("#usual"), async () => {
    const l = await getJSON("/static/lags.json", "lags");
    $("#usual-meta").textContent = `${ym(l.from)} – ${ym(l.to)}`;
    $("#usual").innerHTML = `<div class="table-scroll"><table><thead><tr><th class="num">Days after</th><th class="num">Fund classes</th><th class="num">Net assets</th><th class="num">Gross flow</th></tr></thead><tbody>${
      l.by_lag.map((x) => `<tr><td class="num">${x.lag}</td><td class="num">${pct(x.count.mean, 1)}<span class="sub">${pct(x.count.min, 0)}–${pct(x.count.max, 0)}</span></td><td class="num">${pct(x.pl.mean, 1)}</td><td class="num">${pct(x.gross_flow.mean, 1)}</td></tr>`).join("")
    }</tbody></table></div>`;
  });
  render();
  usual();
  return { refresh: render };
}

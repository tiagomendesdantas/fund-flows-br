// Reporting: how much of each recent day is in, when reports usually arrive, and what each new
// version of CVM's file added and changed.
import { fill, getJSON, skeleton } from "../api.js";
import { dayOnly, esc, fmtDayTime, monthOnly, pct, sbn } from "../fmt.js";

export default function reporting(main) {
  main.innerHTML = `
    <h1 class="view">Reporting</h1>
    <p class="sub">Funds send CVM a daily report, mostly on the business day after; CVM rewrites its file every morning with what has arrived, including resubmissions that change earlier figures. This page shows how complete the latest days are and what each file changed.</p>
    <div class="grid">
      <section class="card span-6" aria-labelledby="h-now">
        <div class="card-head"><h2 id="h-now">The latest days</h2><span class="meta" id="now-meta"></span></div>
        <div id="now">${skeleton("text")}</div>
      </section>
      <section class="card span-6" aria-labelledby="h-usual">
        <div class="card-head"><h2 id="h-usual">When reports usually arrive</h2><span class="meta" id="usual-meta"></span></div>
        <div id="usual">${skeleton("text")}</div>
      </section>
      <section class="card span-12" aria-labelledby="h-files">
        <div class="card-head"><h2 id="h-files">What each file added and changed</h2><span class="meta">daily report, latest 12 versions</span></div>
        <div id="files">${skeleton("text")}</div>
      </section>
    </div>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#now"), async () => {
    const r = await getJSON("/api/reporting", "reporting");
    $("#now-meta").textContent = r.file_day ? `CVM file of ${dayOnly(r.file_day)}` : "";
    $("#now").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Day</th><th class="num">Business days since</th><th class="num">Fund classes in</th><th>Share of the usual</th></tr></thead><tbody>${
      r.completeness.map((d) => `<tr><td>${dayOnly(d.dt)}</td><td class="num">${d.lag}</td><td class="num">${d.n.toLocaleString("en-GB")}</td><td><div style="display:flex;align-items:center;gap:8px"><div class="bar-meter" style="flex:1"><span style="width:${Math.round((d.share || 0) * 100)}%"></span></div><span class="small num" style="min-width:44px;text-align:right">${pct(d.share, 1)}</span></div></td></tr>`).join("")
    }</tbody></table></div><p class="note">The usual count is the median of the about-complete days among the previous 30. Fund classes open and close, so a complete day can sit slightly above or below it.</p>`;
    $("#files").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Written by CVM</th><th>Month</th><th class="num">Fund-days added</th><th class="num">Fund-days changed</th><th class="num">Change in subscriptions</th><th class="num">Change in redemptions</th></tr></thead><tbody>${
      r.releases.map((x) => `<tr><td>${fmtDayTime(x.written)}</td><td>${monthOnly(`${x.month.slice(0, 4)}-${x.month.slice(4)}`)}</td>${x.bootstrap
        ? `<td class="num">${x.new.toLocaleString("en-GB")}</td><td colspan="3" class="small muted">first read of a month already published: a starting point, not new reports</td>`
        : `<td class="num">${x.new.toLocaleString("en-GB")}</td><td class="num">${x.changed.toLocaleString("en-GB")}</td><td class="num">${sbn(x.d_captc, 2)}</td><td class="num">${sbn(x.d_resg, 2)}</td>`}</tr>`).join("")
    }</tbody></table></div><p class="note">A changed fund-day is one whose figures differ from the previous version of the file; the changes are in R$ billion, summed over every day of the month. Every earlier version is kept.</p>`;
  });

  const usual = () => fill($("#usual"), async () => {
    const l = await getJSON("/static/lags.json", "lags");
    $("#usual-meta").textContent = `${monthOnly(`${l.from.slice(0, 4)}-${l.from.slice(4)}`)} – ${monthOnly(`${l.to.slice(0, 4)}-${l.to.slice(4)}`)}`;
    $("#usual").innerHTML = `<div class="table-scroll"><table><thead><tr><th class="num">Business days after</th><th class="num">Fund classes in</th><th class="num">Net assets in</th><th class="num">Gross flow in</th></tr></thead><tbody>${
      l.by_lag.map((x) => `<tr><td class="num">${x.lag}</td><td class="num">${pct(x.count.mean, 1)} <span class="sub">${pct(x.count.min, 0)}–${pct(x.count.max, 0)}</span></td><td class="num">${pct(x.pl.mean, 1)}</td><td class="num">${pct(x.gross_flow.mean, 1)}</td></tr>`).join("")
    }</tbody></table></div><p class="note">From CVM's delivery log: the first time each fund-day was delivered, and the morning file it first appeared in. Average over the months shown, with the range across months. Funds that report late hold about 7% of net assets and move more, relative to their size, than funds on time.</p>`;
  });
  render();
  usual();
  return { refresh: render };
}

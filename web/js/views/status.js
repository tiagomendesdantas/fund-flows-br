// Status: the collector's state, the files read, and every run, failures included.
import { fill, getJSON, skeleton } from "../api.js";
import { esc, fmtDayTime } from "../fmt.js";

const JOB_NAMES = { files: "CVM files", history: "Earlier months", register: "Fund register" };
const STATE_WORDS = { ok: "running", late: "late", failing: "not running" };
const FILE_NAMES = { daily: "Daily report", deliveries: "Delivery log", history: "Daily report, earlier month" };

export default function status(main) {
  main.innerHTML = `
    <h1 class="view">Status</h1>
    <p class="headline" id="state">${skeleton("text")}</p>
    <div class="two">
      <section class="sec" aria-labelledby="h-files">
        <div class="sec-head"><h2 id="h-files">Files read</h2><span class="meta">latest</span></div>
        <div id="files">${skeleton("text")}</div>
      </section>
      <section class="sec" aria-labelledby="h-sched">
        <div class="sec-head"><h2 id="h-sched">Schedule</h2><span class="meta">UTC</span></div>
        <div class="table-scroll"><table><tbody>
          <tr><td class="nowrap">CVM files</td><td>04:10, 05:10, 07:10 and 11:10, every day: the daily report and the delivery log of this month and the last, downloaded only when CVM has rewritten them (03:52 and 04:46 on the days checked)</td></tr>
          <tr><td class="nowrap">Fund register</td><td>10:30, every day</td></tr>
          <tr><td class="nowrap">Earlier months</td><td>Sundays at 12:10: totals of any earlier month whose file CVM rewrote</td></tr>
        </tbody></table></div>
      </section>
    </div>
    <section class="sec" aria-labelledby="h-runs">
      <div class="sec-head"><h2 id="h-runs">Runs</h2><span class="meta">latest, failures included</span></div>
      <div id="runs">${skeleton("text")}</div>
    </section>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#files"), async () => {
    const s = await getJSON("/api/status", "status");
    $("#state").innerHTML = `Collector <span class="${s.collector.state === "ok" ? "" : "attention"}">${esc(STATE_WORDS[s.collector.state] || s.collector.state)}</span>; last successful run ${s.collector.last_success ? fmtDayTime(s.collector.last_success) : "none"}; next check ${s.collector.next ? fmtDayTime(s.collector.next) : "–"}. Times in Brasília.`;
    $("#files").innerHTML = `<div class="table-scroll"><table><thead><tr><th>File</th><th>Written by CVM</th><th>Read</th><th class="num">Rows</th></tr></thead><tbody>${
      s.releases.map((r) => `<tr><td>${esc(FILE_NAMES[r.dataset] || r.dataset)} <span class="mono">${esc(r.month)}</span></td><td class="nowrap">${r.written ? fmtDayTime(r.written) : "–"}</td><td class="nowrap">${fmtDayTime(r.read)}</td><td class="num">${r.rows.toLocaleString("en-GB")}</td></tr>`).join("")
    }</tbody></table></div>`;
    $("#runs").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Job</th><th>Started</th><th>Result</th><th>What happened</th></tr></thead><tbody>${
      s.runs.map((r) => {
        const lines = (r.detail || "").split("\n");
        return `<tr><td class="nowrap">${esc(JOB_NAMES[r.job] || r.job)}</td><td class="nowrap">${fmtDayTime(r.started)}</td><td class="${r.status === "failed" ? "bad" : ""}">${esc(r.status)}</td><td class="small">${esc(lines[0])}${lines.length > 1 ? `<details><summary class="muted">log</summary><pre class="small" style="white-space:pre-wrap;margin:4px 0;font-family:var(--mono);font-size:12px">${esc(r.detail)}</pre></details>` : ""}</td></tr>`;
      }).join("")
    }</tbody></table></div>`;
  });
  render();
  return { refresh: render };
}

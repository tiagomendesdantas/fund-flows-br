// Status: the collector's state, the files read, and every run, failures included.
import { fill, getJSON, skeleton } from "../api.js";
import { esc, fmtDayTime } from "../fmt.js";

const JOB_NAMES = { files: "CVM files", history: "Earlier months", register: "Fund register" };
const STATE = { ok: ["state-ok", "Running"], late: ["state-late", "Late"], failing: ["state-bad", "Not running"] };

export default function status(main) {
  main.innerHTML = `
    <h1 class="view">Status</h1>
    <p class="sub">What the collector has done, the files it read, and every run, failures included. Times in Brasília (UTC−3).</p>
    <div class="grid">
      <section class="card span-6" aria-labelledby="h-files"><div class="card-head"><h2 id="h-files">Files read</h2><span class="meta" id="files-meta"></span></div><div id="files">${skeleton("text")}</div></section>
      <section class="card span-6" aria-labelledby="h-sched"><div class="card-head"><h2 id="h-sched">Schedule</h2><span class="meta">UTC</span></div>
        <div class="table-scroll"><table><tbody>
          <tr><td>CVM files</td><td>04:10, 05:10, 07:10 and 11:10 every day: the daily report and the delivery log of this month and the last, downloaded only when CVM has rewritten them (03:52 and 04:46 on the days checked)</td></tr>
          <tr><td>Fund register</td><td>10:30 every day</td></tr>
          <tr><td>Earlier months</td><td>Sundays at 12:10: totals of any earlier month whose file CVM rewrote</td></tr>
        </tbody></table></div></section>
      <section class="card span-12" aria-labelledby="h-runs"><div class="card-head"><h2 id="h-runs">Recent runs</h2></div><div id="runs">${skeleton("text")}</div></section>
    </div>`;
  const $ = (s) => main.querySelector(s);

  const render = () => fill($("#files"), async () => {
    const s = await getJSON("/api/status", "status");
    const [cls, word] = STATE[s.collector.state] || ["", s.collector.state];
    $("#files-meta").innerHTML = `collector: <span class="${cls}">${esc(word)}</span>`;
    $("#files").innerHTML = `<div class="table-scroll"><table><thead><tr><th>File</th><th>Written by CVM</th><th>Read</th><th class="num">Rows</th></tr></thead><tbody>${
      s.releases.map((r) => `<tr><td>${esc(r.dataset === "deliveries" ? "Delivery log" : r.dataset === "history" ? "Daily report (earlier month)" : "Daily report")} ${esc(r.month)}</td><td>${r.written ? fmtDayTime(r.written) : "–"}</td><td>${fmtDayTime(r.read)}</td><td class="num">${r.rows.toLocaleString("en-GB")}</td></tr>`).join("")
    }</tbody></table></div><p class="note">Next check ${s.collector.next ? fmtDayTime(s.collector.next) : "–"}.</p>`;
    $("#runs").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Job</th><th>Started</th><th>Result</th><th>What happened</th></tr></thead><tbody>${
      s.runs.map((r) => {
        const bad = r.status === "failed";
        const lines = (r.detail || "").split("\n");
        return `<tr><td>${esc(JOB_NAMES[r.job] || r.job)}</td><td>${fmtDayTime(r.started)}</td><td class="${r.status === "ok" ? "state-ok" : bad ? "state-bad" : ""}">${esc(r.status)}</td><td class="small">${esc(lines[0])}${lines.length > 1 ? `<details><summary class="muted">log</summary><pre class="small" style="white-space:pre-wrap;margin:4px 0">${esc(r.detail)}</pre></details>` : ""}</td></tr>`;
      }).join("")
    }</tbody></table></div>`;
  });
  render();
  return { refresh: render };
}

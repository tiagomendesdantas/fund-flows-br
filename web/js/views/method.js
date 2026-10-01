// How the totals are built, what is not covered, and dated notices of every change.
export default function method(main) {
  main.innerHTML = `
  <h1 class="view">Method</h1>
  <div class="two">
  <article class="sec prose">
    <h2>Data</h2>
    <p>Everything comes from CVM's open data portal, under the Open Database License, with no key.</p>
    <ul>
      <li><strong>The daily report of investment funds</strong>: for each fund class and day, net assets, the quota's value, subscriptions, redemptions and the number of quota holdings. One file a month, from January 2021 here. CVM rewrites the current and the previous month every morning with the reports that have arrived since.</li>
      <li><strong>The delivery log</strong>: when each daily report was delivered and whether it replaced an earlier one.</li>
      <li><strong>The fund register</strong>: each class's CVM category and whether it is a fund of funds. Funds closed before the current register began come from the legacy register; together they cover about 97% of net assets in 2021, 98% in mid-2025 and 99.99% in September 2026.</li>
    </ul>
    <p>The collector reads every new version of the current and previous month's file, from 1 October 2026. Each fund-day keeps the figures it had when first published and its latest figures, with every change in between, so the totals as they stood on any morning can be rebuilt.</p>

    <h2>Totals</h2>
    <p>A total is the sum over fund classes. Classes that report by subclass have no class-level row beside them, so nothing is counted twice there. Funds of funds are different: a fund of funds puts its investors' money into other funds in the same report, so adding both counts that money twice. The headline totals leave funds of funds out (about 35% of reported net assets); totals with them are a separate group.</p>
    <p>A group's figure for a day or a month is hidden when fewer than 10 funds reported or one fund made more than half of its subscriptions and redemptions, so that no fund's own figures can be read off a total. No fund is named, ranked or rated anywhere on this site.</p>

    <h2>Reporting lag</h2>
    <p>Funds mostly report on the business day after the day reported. In the file CVM writes on a business-day morning, the day before is under 1% in; the day before that 84–94% of fund classes (about 93% of net assets); 98–99.5% are in by the fifth business day. Days in their first five business days are marked as still arriving everywhere.</p>
    <p>A check runs every morning: the fund-days first delivered before CVM wrote its file, and still active in the delivery log, must be exactly the fund-days in the file. On 1 October 2026 they matched on all 22 days of September. The same rule, applied to the log from January 2025, rebuilds which fund-days each past morning's file held, which is what makes estimates testable on the past; it is checked again on every new file. The log does not give their figures at the time, since a resubmission replaces them.</p>

    <h2>Next</h2>
    <p>Each morning, an estimate of the final total of every day still arriving, with 80% and 95% ranges, published before the late reports come in and graded against CVM's figure two weeks later. The methods, from the simple scale-up to a model of each missing fund, and the rules for choosing between them, will be written down and fixed before the test period is scored.</p>

    <h2>Limits</h2>
    <ul>
      <li>The daily report covers investment funds under CVM's fund rules; receivables funds (FIDC), real estate funds (FII) and private equity funds (FIP) report elsewhere and are not here. Industry figures from other sources, such as ANBIMA's, cover a different set of funds.</li>
      <li>Categories come from the register as it stands now, applied to every year.</li>
      <li>Quota holdings count holdings, not people: an investor in three funds counts three times.</li>
    </ul>
  </article>
  <aside class="sec">
    <div class="sec-head"><h2>Notices</h2></div>
    <dl class="notices" style="margin-top:12px">
      <dt>13–16 Jan 2026</dt><dd><strong>Source gap.</strong> 49 fund classes holding R$1.67 trillion are missing from CVM's file on these four days and present before and after; the totals are short by about R$1.0 trillion of net assets and kept as published. <span class="muted">Checked 1 Oct 2026.</span></dd>
      <dt>1 Oct 2026</dt><dd>Collection starts at 13:49 UTC. September 2026 was read as already published, so its figures are not first-published ones; first-published figures start with the file of 2 October.</dd>
    </dl>
  </aside>
  </div>`;
}

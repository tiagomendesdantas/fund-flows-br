# fund-flows-br

**Data collection, live: deployed.** Brazilian investment fund flows from CVM open data.

CVM publishes its daily fund report every morning before every fund has sent its report. The
file written on the morning of 1 October 2026 held 0.2% of the fund classes for 30 September and
82% for 29 September; the rest arrive over the following week, and more than half of the fund-days
are resubmitted at least once. This project collects every version of the file as it comes out, so
that the figures as first published are kept, and will estimate each day's final industry and
category totals before CVM has received every report, with a public record of how those estimates
compare with the complete figures.

**State on 2026-10-01: collection only.** Totals, estimates and their scorecard come next; until
then the page shows the collector and the files read.

## What this project covers

| Area | Where |
|---|---|
| Scheduled collection with conditional downloads | `src/flows/collect.py`, `src/flows/scheduler.py` |
| Every version of every fund-day kept, with a change log | `src/flows/db.py` |
| A daily check that the delivery log explains the published file | `collect.check_releases` |

## Data

CVM open data, under the Open Database License (ODbL):

- Daily report of investment funds (`FI/DOC/INF_DIARIO`): one row per fund class or subclass and
  day, with net assets, quota value, subscriptions, redemptions and number of quota holders.
- Delivery log (`FI/DOC/ENTREGA`): when each daily report was presented and resubmitted.

Only totals are published here: no fund is named, ranked or rated.

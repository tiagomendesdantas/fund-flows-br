# Data

All data comes from CVM's open data portal (dados.cvm.gov.br) under the Open Database License
(ODbL). Facts below were checked by probing the files on the date given.

## Sources

| Dataset | Files | Content | Refresh |
|---|---|---|---|
| Daily report of investment funds (`FI/DOC/INF_DIARIO`) | `inf_diario_fi_YYYYMM.zip`, monthly from 2021-01; yearly `HIST/inf_diario_fi_YYYY.zip` for 2000–2020 | one row per fund class or subclass and day: `VL_TOTAL`, `VL_QUOTA`, `VL_PATRIM_LIQ` (net assets), `CAPTC_DIA` (subscriptions), `RESG_DIA` (redemptions), `NR_COTST` (quota holders) | current and previous month rewritten Monday to Saturday (03:52 UTC on 2026-10-01), months M-2 to M-11 weekly, older frozen |
| Delivery log (`FI/DOC/ENTREGA`) | `fi_entrega_documento_YYYYMM.zip` from 2025-01; the zip holds the daily report's deliveries in their own CSV (`fi_entrega_documento_diario_YYYYMM.csv`, 158 MB for 2026-09) and other documents in another | every delivery of every document, with `Data_Hora_Entrega` (Brasília time), `Tipo_Apresentacao` (first presentation or resubmission) and `Ativo` | daily (04:46 UTC on 2026-10-01) |
| Fund register (`FI/CAD`) | `registro_fundo_classe.zip`: `registro_fundo.csv`, `registro_classe.csv`, `registro_subclasse.csv` (Latin-1) | funds, classes (with `Classificacao`, `Classe_Cotas`, `Exclusivo`, `Publico_Alvo`) and subclasses after CVM Resolution 175 | Tuesday to Saturday |

Conventions: `;`-separated CSV; ISO dates; `.` decimals. The daily report's CNPJs are punctuated
and the register's are digits only; both are stored as 14-digit integers. Daily files are fetched
with a conditional GET on their ETag; CKAN's `last_modified` field does not match the files' own
`Last-Modified` and is not used.

## What the delivery log explains (checked 2026-10-01)

The file published on the morning of 2026-10-01 (written 03:52 UTC) holds exactly the fund-days
whose first delivery of any kind came before it was written and which still have an active
delivery (`Ativo = S`), leaving out `CLASSES FIIM`, which is delivered as a daily report but is not
in the file. All 22 days of September 2026 match. The two refinements came from that check:

- 15 fund-days had been delivered before the cutoff but every delivery was inactive: they are not
  in the file (withdrawn).
- 27 subclass fund-days had resubmissions but no first presentation in the log: their first
  delivery counts.

So, from January 2025, which fund-days each morning's file held can be rebuilt from the log. Their
values at that time cannot: a resubmission replaces the earlier values, and 57% of September 2026's
fund-days were resubmitted at least once (288,077 of 509,649). The values as first published exist
only where this collector read them, from 2026-10-01.

## Collection

- Each new version of a monthly file is a release. A fund-day keeps the values of the release it
  first appeared in and its latest values; every change is logged with the release that made it.
- The first read of a month that was already being published (September 2026) is marked as a
  bootstrap: its values are not first-published ones.
- The delivery log is kept by file month, because a fund-day can appear in two months' files.

## Checks (scripts/checks.py, 2024-01 to 2026-09, run 2026-10-01)

| Check | Result | Rule adopted |
|---|---|---|
| Subclass rows | From October 2024 some classes report by subclass (18,516 rows in 2026-09). A class with subclasses has no class row beside them (3 exceptions in 2025, out of 115,895 class-days with subclasses). | Subclass rows are exclusive: totals are the sum of all rows. |
| Key and calendar | No duplicate (CNPJ, subclass, day) in any month. Every day with rows is a business day of the calendar in `flows.calendar` (national holidays, Carnival, Corpus Christi), and every business day has a full set of rows except the latest days, still arriving. | Business days from `flows.calendar`. |
| Identity | On 16.7 million pairs of consecutive business days of the same fund, net assets equal the previous net assets grown by the quota's return plus subscriptions minus redemptions within 0.1% in 99.77% of pairs, and within 1% in 99.92%. No negative subscription or redemption; 698 rows with gross flow above ten times the previous net assets. | Values used as reported; the 698 rows are listed, not removed. |
| CNPJ changes | Of 9,299 funds that stopped reporting, 108 (R$13.6 billion) were followed the next business day by a new fund with the same net assets. | A fund counts as expected for a day only if it reported in the previous 10 business days. |
| Register | 99.999% of net assets on 2026-09-25 match a class in `registro_classe.csv`. By CVM classification: Renda Fixa 73.7%, Multimercado 19.6%, Ações 6.4%, FMP-FGTS 0.1%, Cambial 0.1%. | Segments by `Classificacao`. |
| Funds of funds | Classes marked `Classe_Cotas = S` hold 35.0% of net assets. Their money is invested in other funds in the same file, so adding them counts it twice. | Headline totals leave them out; totals including them are shown second. |
| Exclusive funds | `Exclusivo = S`: 37.7% of net assets. | Kept; a candidate feature (their flows are lumpy). |
| Reporting lag | In the file written on the morning of a business day, the business day before is under 1% in (reports sent the same evening), the day before that 84–94% (by count; 84–96% of net assets), and the one before that 93–99%; 98–99.5% are in by the fifth (ranges across the months of 2025-01 to 2026-09). | Estimates start at lag 2, the first file where a day is mostly in. |
| Late reporters | Fund-days first in at lag 3 or later hold 7.4% of net assets and 7.2% of gross flow (2025-01 to 2026-09), and their absolute net flow is larger relative to their size: 0.75% of net assets on average, against 0.43% for those in by lag 2. | Scaling the reported part up by net assets alone is likely to understate the missing flow; tested in the development backtest. |
| Delivery log files | Each month's file covers that month's competence days only (checked for every month from 2025-01). | Kept by file month all the same. |

## Source gaps

- **13–16 January 2026.** 49 fund classes holding R$1.67 trillion of net assets (about a fifth of
  the industry, and R$1.0 trillion of the totals without funds of funds) are absent from CVM's file
  on those four days, and present on the days before and after. They never arrived: the totals for
  those days are short, and are kept as published. Found from a dip in net assets on 2026-10-01;
  a systematic check for such gaps since 2021 comes with the backtest, and days with a gap will be
  scored separately, under a rule written before the test is run.
- **Funds missing from both registers ("Unclassified").** Mostly classes being wound up: in August
  2026, 363 such classes reported, 152 stopped before the month's last week, and their redemptions
  far exceed their assets at the end. Of their large redemptions (above R$100 million on a day),
  R$2.5 billion of R$10.6 billion reappeared the same day as a subscription within 0.5% of the same
  amount in a registered class, as a merger would; the totals without funds of funds net those out.

# Evaluation plan: estimating a day's final fund flows before CVM has them all

Committed on 2026-10-01, before any backtest ran. The plan above the change log is left as
committed; every later decision, result and correction is a dated entry in the change log.

## The task

Each morning CVM publishes its daily fund report with the latest days incomplete. For a competence
day d seen from the morning of business day m, k business days later ("lag k"), estimate the
day's **final** totals of subscriptions (`captc`), redemptions (`resg`) and net flow, by segment
(all funds; funds without funds of funds, the headline; each CVM category of those), with 80% and
95% intervals. Lags scored: k = 2, 3, 4 and 5 (at k = 1 under 1% of funds are in; by k = 5 about
99%).

## Windows

- **Development:** competence days of 2025, from the 11th business day of January (the first ten
  lack history) to 31 December.
- **Frozen test:** competence days of 2026-01-01 to 2026-08-31, scored **once**, after the
  development results are recorded below. 2026-09 is never scored (its truth is incomplete).
- Freeze date of the data: 2026-10-01. The input files are pinned by hash (appendix).

## What a morning knew: vintages

A fund-day is in the file CVM wrote on morning m when its first delivery of any kind came before
the file was written and a delivery is still active (`Ativo = S`), leaving out `CLASSES FIIM`.
This reproduced the published file exactly on 22 days (DATA.md).

- `cutoff(m)` = 00:52 Brasília on m, the observed write time; a sensitivity check at 00:00 and
  03:00 is reported (in 2025, 0.50% of fund-days were first delivered between 00:00 and 00:52 and
  0.45% between 00:52 and 03:00). Live, the cutoff is each file's own write time.
- Every feature and every "last known" value is taken from the fund-days known at m. The final
  file is never consulted for what a method may know.
- Values are the latest file's: resubmissions cannot be undone for the past. Membership is exact,
  values are final; development errors and intervals are therefore optimistic by the size of the
  revisions, which the live collector measures from October 2026 on.

## Expected and missing funds

- Expected for d at m: the funds (CNPJ, subclass) present on at least one of the 10 business days
  before d in the file of m, with `days_since_seen` and their last net assets (`pl_last`).
- A fund that stopped and was followed on the next business day by a fund not seen before with
  net assets within 0.5% is a CNPJ change, not a late report: dropped from the expected set.
- Missing = expected and not present. A fund-day that never arrives has a true flow of 0.
- Funds that arrive without being expected (new funds, returners) are in the truth and in no
  method; their net flow is measured by k and reported as a bias term.

## Truth

The segment sums over the fund-days of d in the file written 15 business days after d, at the
pinned values. This is the live grading rule (first file on or after d + 15 business days), so
later arrivals (about 0.3% of net assets) are left out consistently and the target is frozen. The
difference to the final file is reported.

## Exclusions

Non-business days; segment-days hidden by the small-cell rule (fewer than 10 funds, or one fund
above half of gross flow); the first 10 business days of a window; **gap days**, where funds
present within 5 business days on both sides are absent and hold more than 1% of the day's net
assets. The detector over 2021-01 to 2026-09 found one gap: 13–16 January 2026 (43–48 classes,
14.6–14.8% of net assets each day). Those four days are in the test window and are scored
separately, never in the main scores.

## Methods

All methods are estimated for the same (segment, d, k) cells; a cell any method lacks is dropped
for all.

1. **reported**: the sum of what is in.
2. **scale_up**: within each (category, fund-of-funds) group, reported × (present + missing net
   assets) / present net assets, the factor capped at 3.
3. **trailing**: reported + Σ over missing funds of `pl_last` × their trailing 20-business-day
   mean rates of subscriptions and redemptions (from the vintage); a fund without history takes
   the mean rate of the missing funds of its category.
4. **trailing_beta**: trailing + per category β × (the category's reported net rate that day) ×
   `pl_last`, β fitted by weighted least squares on the training folds.
5. **model**: reported + Σ LightGBM predictions, one model per leg (`captc`, `resg`), target =
   flow / `pl_last` winsorised at the 99.9th percentile of the training rows, Tweedie objective,
   `sample_weight = pl_last`, trained only on fund-days actually missing at k.
   - Features: log `pl_last`; trailing 20-day mean subscription and redemption rates; share of
     zero-flow days; days in the trailing window; `days_since_seen`; k; month-end flag (last three
     business days) and business days to month end; exclusive flag; fund-of-funds flag; CVM
     category; the category's reported subscription, redemption and net rates that day; the
     category's share of expected net assets already in.
   - Fixed hyperparameters: learning rate 0.05, 63 leaves, 200 minimum rows per leaf, feature
     fraction 0.9, bagging 0.8, L2 1.0, 400 rounds, seed 20261001. The Tweedie variance power is
     chosen among 1.3, 1.5 and 1.7 on the development year by the primary metric.
   - Cross-fitting on development: 5 contiguous blocks of ISO weeks; training rows at least one
     week away from the held-out block; every estimate scored is out of fold.
   - For the test and for live use, the model is fitted on all development rows with the chosen
     power.

## Primary metric and the decision

- **Primary metric:** mean absolute error of net flow, in reais, for the `direct` segment at lag 2,
  over the scored days.
- **Skill** of a method against `scale_up`: 1 − Σ|e_method| / Σ|e_scale_up| over paired days.
- **Interval:** block bootstrap by ISO week (about 50 blocks), 2,000 resamples with replacement
  of whole weeks, seed 20261001, percentiles 2.5 and 97.5.
- **Decision:** the model (at its best power) becomes the default shown live if its skill is at
  least 0.10 and the 2.5th percentile of its skill is above 0. Otherwise the default is whichever
  of `scale_up`, `trailing` and `trailing_beta` has the lower primary MAE. The script applies the
  rule; no hand adjustment.
- Reported, not decisive: skill by category, by lag, with month blocks; MAE in basis points of net
  assets; bias; pinball loss at the four quantiles; interval coverage.

## Intervals

Empirical 2.5th, 10th, 90th and 97.5th percentiles of (truth − estimate) / missing net assets for
the default method, by measure and month-end flag, pooled across lags and categories, fitted on
the development year and frozen in `models/intervals.json`. Targets: 80% intervals cover 70–90%
and 95% intervals 90–99% of test days. Live: after 60 graded days, if 80% coverage is outside
70–90%, the intervals are refitted on development plus live residuals and the change logged here.

## The one-shot test

The test runs once, with `scripts/backtest.py --test --once`, only after this file carries the
development results; the script refuses a second run. Its outputs are committed with the
estimates' hash. Any later change to a method is a new version with a new entry here, never a
re-score of the frozen test.

## Live grading

Each morning's estimates are stored as issued. A day is graded against the first file written on
or after d + 15 business days, once, and never re-graded. Revisions after that are a separate
statistic. The register as of the issue day defines categories.

## Known limitations

- Development values are final values (membership exact, values final).
- One register snapshot (2026-10-01) classifies every year; a fund's category or fund-of-funds flag
  may have changed.
- The cutoff is a single observed write time.
- The administrator's same-day flow was left out of the model's features: when an administrator
  is late, it is late for all its funds, so the feature is mostly empty when needed. An ablation
  may be reported, not used.

## Change log

**2026-10-01 — plan committed before any backtest run.** Inputs: the daily files 2024-01 to
2026-09 and the delivery logs 2025-01 to 2026-10, hashed below.

**2026-10-01 — development run done; results under "Development results".** No change to the plan.

## Development results

**2026-10-01 — the development year (2025), run once under the plan above** (`scripts/backtest.py
--dev`; estimates sha256 `10b472539109652e`; outputs in `docs/backtest/dev/`). 242 days, lags 2–5,
49,336 scored cells, 906,535 model rows, no gap days, every fund-day matched to a delivery.

Primary metric, lag-2 `direct` net MAE: reported R$1.158 bn; scale_up 1.197; model 1.27 (power 1.7,
best of three; skill against scale_up −0.063, interval [−0.175, +0.028]); trailing 1.48;
trailing_beta 1.45. **The model fails the rule; the default is scale_up.** The plain reported sum
has skill +0.033 against scale_up (interval [−0.027, +0.092]): not distinguishable, and it was not
in the candidate set for the default; it stays on every page as the reference line.

Reading: at lag 2 the missing funds hold 5.4% of net assets (median) and their net flows nearly
cancel, so the file's own sum is within R$1.2 bn of the final figure on an average day (1.4 bps of
net assets; the median daily net flow is R$7.9 bn). Scale-up adds error by inflating both legs
(bias −0.28 bn against −0.15 for reported). The model's gain comes from each fund's own trailing
rates (46–47% of importance per leg), then its size; category and calendar features add little.
Unexpected arrivals (funds not in the expected set) add +0.53 bn of net flow at lag 2 and +0.29 at
lag 5: a positive bias no method captures, logged as a candidate for a later version, not applied.

Intervals for scale_up (`models/intervals.json`), in-sample coverage: 80% level: captc 79.4%, resg
77.5%, net 74.6%; 95% level: 92.2%, 90.2%, 87.4%. The net 95% interval is already below its 90–99%
target in-sample; the test will show the out-of-sample shortfall, and the live refit rule applies.

Diagnostics. Cutoff at 00:00 / 00:52 / 03:00: reported 1.168 / 1.158 / 1.136 bn, scale_up 1.199 /
1.197 / 1.168: immaterial. Truth at d+15 against the final file, `direct` net: mean +0.03 bn, MAE
0.12, largest 2.6.

For the test (Phase 4): default scale_up with these intervals; all five methods scored on the same
cells; 13–16 January 2026 scored separately as gap days.

## Appendix: pinned inputs (SHA-256, first 16 hex digits)

| File | Hash |
|---|---|
| `fi_entrega_documento_202501.zip` | `0fb464d74fadb685` |
| `fi_entrega_documento_202502.zip` | `799993f5987b4462` |
| `fi_entrega_documento_202503.zip` | `bbfc6bde14f910dc` |
| `fi_entrega_documento_202504.zip` | `4635c507b1a6a051` |
| `fi_entrega_documento_202505.zip` | `371e64963d21e8ec` |
| `fi_entrega_documento_202506.zip` | `1f6fa31dff14fc9b` |
| `fi_entrega_documento_202507.zip` | `dbce7502a738a967` |
| `fi_entrega_documento_202508.zip` | `98c176fba0999b64` |
| `fi_entrega_documento_202509.zip` | `1db1764ae00279e4` |
| `fi_entrega_documento_202510.zip` | `e52c98b859f555f8` |
| `fi_entrega_documento_202511.zip` | `1100df796b762609` |
| `fi_entrega_documento_202512.zip` | `d0618a108a9dab31` |
| `fi_entrega_documento_202601.zip` | `364c3a0fba8cc731` |
| `fi_entrega_documento_202602.zip` | `611a757fec2a06c3` |
| `fi_entrega_documento_202603.zip` | `adf3e9f7d2561be0` |
| `fi_entrega_documento_202604.zip` | `411bde84cea2057c` |
| `fi_entrega_documento_202605.zip` | `540fde7a96001ba5` |
| `fi_entrega_documento_202606.zip` | `4944a4fcdc9174dc` |
| `fi_entrega_documento_202607.zip` | `be1d33562d64fd7d` |
| `fi_entrega_documento_202608.zip` | `b2dd62a1184a132a` |
| `fi_entrega_documento_202609.zip` | `51511d72dddfb355` |
| `fi_entrega_documento_202610.zip` | `6dfd2cfc39c9f65a` |
| `inf_diario_fi_202401.zip` | `7f5e2418df5bf99b` |
| `inf_diario_fi_202402.zip` | `1fa01711c44a3343` |
| `inf_diario_fi_202403.zip` | `cd58af7e0ad4d861` |
| `inf_diario_fi_202404.zip` | `1af9b96e5aae87b2` |
| `inf_diario_fi_202405.zip` | `2e16eb801932591b` |
| `inf_diario_fi_202406.zip` | `973d065f3d39d137` |
| `inf_diario_fi_202407.zip` | `bc9409a3e1a4e7b9` |
| `inf_diario_fi_202408.zip` | `6136da4e3baf7397` |
| `inf_diario_fi_202409.zip` | `2621376346c195ce` |
| `inf_diario_fi_202410.zip` | `93402772bab6aa59` |
| `inf_diario_fi_202411.zip` | `92f64d32c44fc84d` |
| `inf_diario_fi_202412.zip` | `b3c7d68abbc9d103` |
| `inf_diario_fi_202501.zip` | `5d1860e2739bb05b` |
| `inf_diario_fi_202502.zip` | `3812e275e51bf1a9` |
| `inf_diario_fi_202503.zip` | `4415b7871050234c` |
| `inf_diario_fi_202504.zip` | `956b56781822d0ca` |
| `inf_diario_fi_202505.zip` | `32d6027935ca83df` |
| `inf_diario_fi_202506.zip` | `6cb834789a32a18d` |
| `inf_diario_fi_202507.zip` | `c345508feb64863a` |
| `inf_diario_fi_202508.zip` | `de0f24d23a2b86cd` |
| `inf_diario_fi_202509.zip` | `5907ab2b5bfd2138` |
| `inf_diario_fi_202510.zip` | `6b8b700d8ca251c7` |
| `inf_diario_fi_202511.zip` | `9843d6fb5f2f74f6` |
| `inf_diario_fi_202512.zip` | `dc18584c7e6a8b5b` |
| `inf_diario_fi_202601.zip` | `06cee843fc282193` |
| `inf_diario_fi_202602.zip` | `79069e31024e60e1` |
| `inf_diario_fi_202603.zip` | `907de3e8f48c414d` |
| `inf_diario_fi_202604.zip` | `4d45e325314901f7` |
| `inf_diario_fi_202605.zip` | `f252b94a67eec82f` |
| `inf_diario_fi_202606.zip` | `0a9ddc23ea3fd50d` |
| `inf_diario_fi_202607.zip` | `9d411eacf2256e5c` |
| `inf_diario_fi_202608.zip` | `342d92afe9778ce6` |
| `inf_diario_fi_202609.zip` | `ef61166c2ee23b8a` |
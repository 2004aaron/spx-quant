# Mission, Milestone OKRs and Grading Criteria

Sections 6 and 7 of the proposal, revised November 2026. Beta, RC and Stretch KRs differ
from the September 27 final proposal.

## Mission

Give a self-directed SPX option seller a personalized, professional-level analysts read on
when to sell, how much to sell, and when to stay out of the market.

## Alpha Objective (Proposal Centric, release October 19)

The advisor produces complete, sized proposals or reasoned stand-downs from analysis
performed on live data. (Focus: Proposals exist, are actionable, and match account type)

### A-KR1: 10 proposals or stand-downs with strategy, amounts, and rationale

- **Measure:** trading days, out of the 10 running October 5 to 16, on which both the 10:30
  Pacific scan and the end-of-day scan produced either a complete proposal or a stand-down
  with attached rationale.
- **Baseline:** 0.
- **Target:** 10 of 10 by October 19.
- **Verification:** a script counts the qualifying days in the log, and its output is committed.
- **Connects:** US-02, US-03, US-04, US-06.

### A-KR2: 0 proposals generated that cannot be entered or bought

- **Measure:** the number of proposals logged October 5 to 16 that fail an entry check.
  - Account limits check: buying power is at or under the per-position cap, and
    delta-to-theta is within the limit.
  - Market state check: both legs are listed with a bid above 0, pass the liquidity filter,
    and have a quote under 30 minutes old. The credit falls between the combined bid and the
    combined ask. End-of-day proposals are checked against the next 10:30 scan's quotes.
- **Baseline:** none of the 15 shadow-log proposals can be checked, because the log stores no
  contracts, buying power, or bid/ask.
- **Target:** 0 failures across at least 10 proposals by October 19.
- **Verification:** a check script run over the log, with its output table committed. One
  planted bad row per check fails in the same run.
- **Connects:** US-01, US-03, US-06.

### A-KR3: 24 account type and size tests pass during proposal generation

- **Measure:** violations of the buying-power cap or the delta-to-theta limit across 24 test
  cases covering 4 account sizes, 2 margin types, and 3 market regimes.
- **Baseline:** the suite does not yet exist.
- **Target:** 24 cases implemented with 0 violations by October 19.
- **Verification:** the automated test suite and its committed results table.
- **Connects:** US-01, US-03.

## Beta Objective (Notification Centric, release November 16)

Every recommendation is delivered through a messaging system along with the quotes it was
constructed on and a timestamp for the data and the output. (Focus: Alerts are fast,
consistent, and time-informative)

### B-KR1: 95% of alerts reach the user within 5 minutes of scan completion

- **Measure:** percentage of messages (alert/proposal emails/notices) delivered within 5
  minutes of scan completion between October 30 and November 15. This does not include the
  weekly report and the daily paper P/L emails since those are not scan based emails and I am
  still configuring the information layout to make it more legible and I am currently within
  the targets window.
- **Baseline:** no delivery mechanism exists.
- **Target:** 95% or more by November 16.
- **Verification:** delivery timestamps compared against scan timestamps in the log.
- **Connects:** US-07.

### B-KR2: All 22 scheduled scans produce a message

- **Measure:** scheduled scans from October 30 to November 13 (11 trading days, 2 scans a day)
  that send a proposal, a stand-down, or a "no advice" notice with its reason. This narrows the
  potential for valid scan counts because if it starts 30 minutes after its allotted slot, the
  engine already logs a `scan_late` event.
- **Baseline:** 0, since no delivery exists.
- **Target:** 22 of 22 by November 16.
- **Verification:** a script matches the scan schedule against sent messages as well as the
  count of `scan_late` events, and its output is committed.
- **Connects:** US-04, US-06, US-07, US-12.

### B-KR3: 0 alerts are missing their quotes or their data and output timestamps

- **Measure:** percentage of alerts from October 30 to November 13 that include:
  - the quotes used (SPX spot, VIX9D, VIX, VIX3M, and each leg's bid/ask for proposals);
  - for proposals, the trend reading the engine found, the strategy employed, the SPX 50-day
    and 200-day averages;
  - the data timestamp;
  - the output timestamp.
- **Baseline:** 0%.
- **Target:** 100% by November 16.
- **Verification:** a script checks each sent message for those fields, and its output is
  committed.
- **Connects:** US-02, US-03, US-07, US-08.

## Release Candidate Objective (Market Success, release December 9)

Run two paper accounts of different sizes, a small one that can only fit XSP and a larger one
that can carry SPX. Each takes every proposal the engine sends, so results measure the
engine's sizing and risk estimates.

### RC-KR1: Under 10% of proposals hit their stated worst case

- **Measure:** percentage of proposals logged from October 5 onward whose worst daily
  mark-to-market loss met or exceeded the worst case predicted at proposal time across both
  accounts and sizing suggestions.
- **Baseline:** not measurable, since the shadow log stores no predicted worst case.
- **Target:** under 10% by December 9.
- **Verification:** the predicted-against-realized table in the weekly report.
- **Connects:** US-05, US-09, US-11.

### RC-KR2: Daily engine position values land within 5% of market value

- **Measure:** mean absolute difference between the engine's daily prediction of where the
  value of the option should be, and the broker's mark for the same position at market close.
  I will be building script to pull the market data from TastyTrade (since it allows API calls).
- **Baseline:** unmeasured.
- **Target:** 5% or less by December 9.
- **Verification:** a comparison script over the pilot window, with its error table committed.
- **Connects:** US-09, US-11.

### RC-KR3: Decisions are reflected in the weekly report

- **Measure:** number of proposals on file that have an indicator showing that the email was
  answered with the investor's decision. The proposals will all be marked as accepted for now
  since I am accepting all the proposals on a paper account for the sake of testing the
  engine's accuracy. This means the file of proposals generated and exported via email should
  match the number of open trades.
- **Baseline:** no reply mechanism or file exists.
- **Target:** at most 1 missing decision and 0 mismatches by December 9.
- **Verification:** a script compares sheet rows against delivered alerts and the report's
  active-positions list.
- **Connects:** US-08, US-10, US-11, US-13.

## Stretch Key Results (only after the core is complete)

These measure the two stretch stories. They are graded only if the core KRs above are met.

### S-KR1: 0 proposals exceed remaining buying power

- **Measure:** proposals from October 5 onward whose buying power exceeds what is available.
  - Available buying power: net liquidation minus the buying power held by positions logged
    as taken and not yet closed.
  - This is a stretch because it will limit testing on the accuracy side because the accounts
    will hit a buying power limit and have to wait for contracts to expire and the money to
    become free before it can hold another contract.
- **Baseline:** 0/no functionality.
- **Target:** 0 failures across at least 10 proposals by December 9. A proposal that would go
  over is sized down, or replaced by a stand-down with the reason "insufficient buying power."
- **Verification:** the A-KR2 check script with a remaining-buying-power check added, plus
  planted bad rows.
- **Connects:** US-01, US-03, US-10, US-13.

### S-KR2: Percentage advantage of strategic contract expiration

- **Measure:** total P/L of the staggered book minus the stacked book, reported with:
  - the difference in dollars and as a percentage of credit;
  - a block-bootstrap p-value;
  - each book's worst single-day loss.
- **Baseline:** no tracking of this data currently.
- **Target:** a report published by December 9, whatever the result. "No established
  difference" counts as a valid finding.
- **Verification:** the comparison script and its results table, committed. Both books use the
  same entry days, deltas, sizing, and exit rules, so expiration is the only thing that differs.
- **Connects:** US-09, US-11, US-14.

## Grading Criteria

Bands cover every outcome without gaps or overlaps. Higher is better unless the row says
lower. Where a row has two numbers, the grade is the highest band where both hold. A minimum
in the F column overrides the other bands. Stretch rows are graded only after the core KRs are
met. I won't redefine a target or band after seeing results.

| KR | Metric and evidence | A | B | C | D | F |
| --- | --- | --- | --- | --- | --- | --- |
| A-KR1 | Days complete (of 10); log script | 10 | 9 | 8 | 6–7 | 0–5 |
| A-KR2 | Failed proposals, out of 10+ (lower is better); check script | 0 | 1 | 2 | 3–4 | 5+, under 10 proposals, or a planted row passes |
| A-KR3 | Cases built (of 24) and violations (lower is better); test results | 24 cases, 0 violations | 24 cases, 1 violation; or 20–23 cases, 0 | 24 cases, 2–3 violations; or 20–23 cases, 1–3 | 20+ cases, 4–6 violations | 7+ violations, or under 20 cases |
| B-KR1 | Messages on time ÷ messages sent; log timestamps | 90%+ | 80–89% | 70–79% | 50–69% | Under 50% |
| B-KR2 | Scans that sent a message (of 22); schedule check | 22 | 21 | 19–20 | 16–18 | 0–15 |
| B-KR3 | Alerts with quotes and both timestamps ÷ alerts sent; message check | 100% | 90–99% | 80–89% | 70–79% | Under 70% |
| RC-KR1 | Proposals past worst case ÷ proposals marked (lower is better); report table | Under 10% | 10–15% | 16–20% | 21–29% | 30%+, or under 20 proposals marked |
| RC-KR2 | Mark error, % of credit (lower is better); error table | 5.0% or less | Over 5.0 to 7.5% | Over 7.5 to 10.0% | Over 10.0 to 15.0% | Over 15.0%, or under 20 position-days |
| RC-KR3 | Missing decisions and mismatches (lower is better); sheet check | ≤1 missing, 0 mismatches | ≤3 missing, 0 mismatches | ≤5 missing, ≤1 mismatch | ≤8 missing, ≤2 mismatches | Anything worse |
| S-KR1 | Proposals over available buying power, out of 10+ (lower is better); check script | 0 | 1 | 2 | 3–4 | 5+, or under 10 proposals |
| S-KR2 | Parts in the committed comparison (of 4: both books from Oct 5, difference in $ and %, p-value, worst day per book) | 4 of 4 | 3, including the difference | 2, including the difference | Books logged, no difference reported | No staggered book |

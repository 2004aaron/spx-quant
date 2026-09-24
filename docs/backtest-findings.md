# Backtest findings, first validation pass (September 7, 2026)

Run against free data only: Cboe's published daily histories of its strategy
indices and VIX indices, DoltHub's public SPY option-chain database (2019 to
present), and Yahoo daily closes. The scripts that produced these tables
(`sources.py`, `prefetch.py`, `regime_study.py`, `significance.py`,
`validate_model.py`, `harness.py`) will be re-added to this repository under
US-10 so that a reviewer can regenerate every table from a clean clone.

## Tier A: does the regime gate work?

3,941 sessions, 2011 to 2026, forward horizon 21 sessions, signals lagged one day.
The production classifier was imported, not reimplemented. Significance is a
circular block bootstrap with 21-session blocks.

### 1. The gate does not separate good months from bad

| Program | GO | STAND DOWN | difference | p |
| --- | --- | --- | --- | --- |
| PUT (ATM monthly put) | 8.25% | 8.53% | -0.27 pp | 0.938 |
| PUTD (30-delta put) | 10.37% | 13.52% | -3.15 pp | 0.453 |
| WPUT (ATM weekly put) | 4.09% | 6.61% | -2.52 pp | 0.502 |
| CNDR (iron condor) | 1.54% | -0.93% | +2.47 pp | 0.345 |
| BXMD (30-delta buywrite) | 9.71% | 12.33% | -2.62 pp | 0.553 |

Nothing here is distinguishable from noise, and for every naked short-premium
program the sign is negative.

### 2. Backwardation is the best regime for short premium, not the worst

| Program | contango | flat | backwardation | difference | p |
| --- | --- | --- | --- | --- | --- |
| PUT | 6.94% | 9.94% | 16.19% | +9.25 pp | 0.059 |
| PUTD | 8.73% | 13.11% | 26.66% | +17.92 pp | 0.004 |
| BXMD | 8.38% | 12.06% | 23.03% | +14.65 pp | 0.015 |
| CNDR | 0.80% | -0.53% | 1.73% | +0.93 pp | 0.796 |

The worst month in backwardation was also less bad than the worst in contango.
The intuition behind "do not get short vega too soon" is about the path of an
inversion, which a management rule can address; refusing the regime outright is a
different and apparently expensive decision. This is why the backwardation
threshold is tagged `unvalidated: tested, not supported` and why US-13 exists.

Cboe's own volatility-managed PutWrite index (PUTVM) rotates strategy by VIX
percentile rather than standing down. Over 19.7 shared years it gave up 38 basis
points of annual return against unmanaged PUT (CAGR 6.82% vs 7.20%) and cut the
maximum drawdown from -37.09% to -30.80%. Regime management, in the exchange's
hands, is risk control rather than alpha.

### 3. Panic reads as the best state on far too little data

51 panic sessions, about two independent months, mostly COVID. Not actionable.

### 4. Crushed vol is the one gate rule that points the right way

PUT -6.50 pp (p=0.194), CNDR -4.37 pp (p=0.182), BXMD -6.98 pp (p=0.251).
Consistent sign, never significant. Tagged `unvalidated: partially supported`.

### 5. Structural choices, 2007 to 2026

| Program | CAGR | ann vol | max DD | worst 21d | Sharpe |
| --- | --- | --- | --- | --- | --- |
| PUTD (30-delta put) | 9.46% | 13.38% | -45.03% | -30.96% | 0.75 |
| SPX (benchmark) | 9.00% | 16.44% | -56.78% | -32.97% | 0.61 |
| PUT (ATM put) | 7.20% | 11.31% | -37.09% | -28.82% | 0.67 |
| WPUT (weekly put) | 4.37% | 10.40% | -28.62% | -24.79% | 0.46 |
| CNDR (iron condor) | 0.90% | 6.80% | -19.72% | -9.50% | 0.15 |
| BFLY (iron butterfly) | -2.25% | 10.76% | -54.92% | | -0.18 |

Naked put side beats condor by +6.58 pp (p=0.007): "prefer strangles over
condors" is the one strategy preference from the mentor's framework that the data
supports. Monthly vs weekly, 30-delta vs ATM, and condor vs butterfly are not
established.

## Tier B: trade-level replay on SPY, 2019 to 2026

327 to 377 delta-matched short strangles, entries every three chain sessions,
opening at the real bid.

### Part A: real entries, real settlement at the actual close

| Variant | n | win % | avg P/L | return on credit | worst | sd |
| --- | --- | --- | --- | --- | --- | --- |
| 16-delta matched, 45 DTE | 327 | 80.1% | +$182 | 32.0% | -$6,762 | $936 |
| 10-delta matched | 327 | 87.2% | +$142 | 42.1% | -$6,024 | $683 |
| 30-delta matched | 327 | 67.3% | +$196 | 16.2% | -$7,591 | $1,376 |
| 16P vs 10C unmatched | 328 | 85.1% | +$198 | 41.1% | -$6,916 | $862 |
| 16-delta, 30 DTE | 377 | 81.7% | +$118 | 28.9% | -$8,229 | $801 |
| 16-delta, 60 DTE | 292 | 81.8% | +$166 | 27.0% | -$7,733 | $1,173 |

45 DTE is the sweet spot (tagged `validated`). Further out of the money is better
risk-adjusted; the 16-delta default is tagged `partially supported`. The unmatched
result is a bull-market artifact (SPY went from 250 to 770), not evidence against
delta matching. Concentration is the whole story: the worst 16 trades (5%)
account for -$51,294 against total gains of +$59,366.

### Part B: management rules, modelled on the real underlying path

Model validated against 69,273 real mark-forward pairs (mean bias -$0.26 per
share); in the wing bucket it runs about 13% rich, which biases against
early-closing rules, so the result below survives the bias.

| Variant | n | win % | avg P/L | return on credit | worst | 5th pct | avg days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Hold to expiry | 327 | 80.1% | +$182 | 32.0% | -$6,762 | -$1,816 | 49.6 |
| Profit target only | 334 | 92.2% | +$152 | 26.8% | -$6,762 | -$634 | 25.7 |
| No loss stop | 334 | 69.2% | +$14 | 2.5% | -$1,856 | -$902 | 13.1 |
| No 21-DTE exit | 334 | 67.7% | +$7 | 1.3% | -$1,856 | -$872 | 12.8 |
| All four rules | 334 | 66.8% | +$0 | 0.0% | -$1,856 | -$872 | 12.6 |

The 50% profit target is the only management rule that earns its place (tagged
`validated`). The 2x loss stop and the 21-DTE defensive exit each cost about 25
percentage points of return on credit; they are expensive tail insurance.

## Honest limits

SPY, not SPX. One bull market with two stress events. Overlapping windows in
Tier A (about 187 independent months, 22 in backwardation, 2 in panic). No
commissions or assignment. Part B is a model. Nothing here tests a portfolio.

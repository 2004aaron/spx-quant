# Rules pivot: what the data said, and what changed (2026-10-19)

Two rule sets in StormGlass came from the playbook, not from evidence: the regime gate (when to sit out) and the exit rules (when to close). The September backtest ([backtest-findings.md](../backtest-findings.md)) said both were costing money. I re-ran the gate test on fresh data, replayed the forward log, and changed the defaults. Jonathan signed off on the changes on October 19.

## The changes

| Rule | Before | After | Where |
|---|---|---|---|
| Backwardation (inverted VIX curve) | STAND DOWN | Shown as a note, scan continues | `gate.stand_down_on`, Alpha (main) |
| VIX below 13 (floor) | STAND DOWN | STAND DOWN (kept) | same |
| VIX at 28 or above (ceiling) | STAND DOWN | STAND DOWN (kept as a risk rail) | same |
| 50% profit target | exit | exit, the only default exit | `management.exit_rules`, Beta (`beta-restore`) |
| 2x loss stop | exit | off by default | same |
| 21-DTE defensive exit | exit | off by default | same |
| Short strike tested (30 delta) | exit | off by default | same |

Every rule is still in the code and can be switched back on in `config/params.toml`. Tail risk is now handled by sizing: each proposal is cut until its stress-test loss (index down 10%, volatility up 10 points) fits inside the account's worst-case cap, 5% of net liquidation by default.

## Evidence 1: the gate re-run (Cboe data through 2026-10-16)

`research/rules-pivot/tier_a.py` runs the shipping classifier (`spx_quant.regime.classify`) over every session from January 2011 to September 2026: 3,945 sessions, signal lagged one day, 21-session forward return of five Cboe strategy indices, which are real recorded results of systematic short premium. Returns are annualized. p-values are a circular block bootstrap with 21-session blocks. Output: [rules-pivot-tier-a.json](rules-pivot-tier-a.json).

| Index | Old gate GO | Old gate STAND DOWN | p | New gate GO | New gate STAND DOWN | p |
|---|---|---|---|---|---|---|
| PUT (ATM monthly put) | 7.31% | 11.22% | 0.28 | 7.28% | 11.77% | 0.25 |
| PUTD (30-delta put) | 9.34% | 16.41% | 0.08 | 9.44% | 16.93% | 0.09 |
| WPUT (weekly put) | 4.25% | 6.74% | 0.44 | 4.19% | 7.21% | 0.38 |
| CNDR (iron condor) | 1.56% | -0.71% | 0.33 | 1.46% | -0.70% | 0.38 |
| BXMD (30-delta buy-write) | 8.79% | 14.84% | 0.16 | 8.94% | 15.10% | 0.18 |

What it says:

- **Backwardation was the best time to sell premium, not the worst.** 245 sessions read backwardation. The 30-delta put index returned 26.4 points a year more in those sessions than in the rest (p = 0.0015). That is the strongest result in the study, and it points the opposite way from the old rule. So it goes.
- **The floor stays.** VIX under 13 was the lowest-return bucket (PUTD about 4.2% a year against 9.9% in the normal bucket), so sitting out thin premium is reasonable even if it's not significant.
- **The ceiling is a judgment call.** Sessions with VIX at 28 or above returned the most (about 46% a year on PUTD) with a 5th-percentile month no worse than normal. But that is 306 overlapping sessions, roughly 15 independent months, mostly rebounds after crashes. I kept it as a risk rail and flagged it for Sprint 3.
- Neither gate separates good months from bad at a level I'd defend. The gate's job now is to refuse obviously bad inputs, not to time the market.

## Evidence 2: the exit rules (September backtest, Tier B part B)

334 SPY strangles, 2019 to 2026, 16 delta, 45 DTE, exits modelled on the real price path.

| Exit setup | Win rate | Return on credit | 5th-pct loss | Worst |
|---|---|---|---|---|
| Hold to expiry | 80.1% | 32.0% | -$1,816 | -$6,762 |
| **50% profit target only (new default)** | **92.2%** | **26.8%** | **-$634** | -$6,762 |
| All four rules (old default) | 66.8% | 0.0% | -$872 | -$1,856 |

The loss stop and the 21-DTE exit each cost about 25 points of return. They capped the single worst trade, which is real, but they paid for it with the entire premium. The profit target alone kept 84% of the hold-to-expiry return and cut the 5th-percentile loss by two thirds.

## Evidence 3: the forward log under both rule sets

The forward benchmark (`shadow-log.jsonl`, real SPX quotes, one lot, mid fills, since 2026-09-07) closed 16 positions by October 15.

| | Old rules (as logged) | Profit target only |
|---|---|---|
| Closed | 16 | 16 |
| Winners | 14 (87.5%) | 16 (100%) |
| Realized P/L | +$45,485 | about +$55,219 |

Every winner closed on the profit target. The 2x stop and the 21-DTE exit never fired. The two losers were both closed by the tested-strike rule on September 21 (-$695 and -$1,975). I priced those same strikes on the October 19 board: they now show +$5,950 and +$5,865, 85% and 82% of credit. Under the new default they'd have stayed open and closed at the 50% target, about +$3,480 and +$3,580. That's a swing of about $9,700 on two trades.

Read this carefully: it's one month, one market, mid fills, no account, and two trades decide the difference. It agrees with the backtest; it doesn't prove anything by itself.

## What this does not fix

- **The big loss is still there.** Profit-target-only had the same -$6,762 worst trade as holding to expiry (COVID, February 2020). The answer is size, not a stop: the 5% worst-case cap limits what any one stress event can take.
- **Open positions are underwater right now.** As of the October 16 mark, 8 of 14 open forward-log positions were losing after VIX moved from about 15 to 20. That is the strategy working as designed: it loses in fast moves and earns when they fade. Neither rule set would have closed them yet.
- **SPY, not SPX, in the backtest.** Everything in Evidence 2 is SPY. OptionMetrics through the library is still the way to re-run it on SPX.

## Reproduce

```
python research/rules-pivot/tier_a.py          # gate re-run, downloads Cboe histories to .cache/cboe
python -m unittest discover -s tests -t .       # includes the new gate and exit tests
```

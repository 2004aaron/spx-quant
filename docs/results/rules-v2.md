# Rules v2: what the SPX backtests changed (2026-10-20)

The rules pivot on October 19 changed the gate and the exits. This round changes what the engine builds. It rests on three studies run on OptionsDX SPX end-of-day chains, 2010 to 2023:

- [`tier-b-spx-2010-2023.md`](tier-b-spx-2010-2023.md): strangle replay and the VIX futures curve.
- [`all-strategies-spx-2010-2023.md`](all-strategies-spx-2010-2023.md): all four builders, with the production strike selection and margin model.
- The trend and end-to-end tests below.

Every rule is still in `config/params.toml` and can be switched back.

## The changes

| Rule | Before | After | Where |
|---|---|---|---|
| Target expiry | 45 DTE (30 to 60) | 60 DTE (45 to 75) | `expiry` |
| Iron condor | in every playbook bucket | removed | `playbook` |
| Naked put | blocked by the 1:2 delta:theta limit | offered when the SPX 50-day is above the 200-day, with a 1:0.5 limit, ranked first | `trend` (new) |
| Downtrend or unreadable trend | n/a | naked put not offered; strangle as before | `trend.up_only` |
| Thin structures | proposed if the mid looked good | rejected if the natural fill gives up more than 25% of the mid credit | `liquidity.max_fill_cost_pct` |
| Put vertical | 25-delta short, wings 0.75% of spot; blocked by the 1:2 limit | 16-delta short, wings 5% of spot; offered in an uptrend with a 1:0.25 limit | `put_vertical`, `trend` |

The alert now shows the trend under MARKET, says why the naked put and put vertical were or weren't offered, and flags when the delta:theta limit was relaxed. In an uptrend the naked put is ranked first when it fits; the vertical is the defined-risk fallback for accounts too small for a naked position. The engine's own risk checks (expected value, probability of profit, worst-case cap) still apply to both.

## Evidence 1: 60 DTE beats 45 for every structure that works

Annual return on portfolio-margin buying power, 50% profit target, bid/ask fills.

| Structure | 45 DTE | 60 DTE | Held up in 2010-2018 and 2019-2023? |
|---|---|---|---|
| Strangle | 30.1% | 46.5% | Yes (36.3 to 46.7; 23.9 to 46.3) |
| Naked put | 63.6% | 85.8% | Yes (67.7 to 79.5; 59.5 to 91.9) |

Worst trade got smaller at 60 DTE for both (strangle -$82,469 to -$77,670; naked put -$66,372 to -$61,132).

## Evidence 2: the iron condor doesn't pay

2.9% return on credit at mid fills, -53.4% at bid/ask, negative held to expiry even at mid. Cboe's condor index (CNDR) was also the weakest program in the September Tier A study. Out.

## Evidence 3: the naked put, and when not to sell it

The naked put returned 63.6% a year on buying power against the strangle's 30.1% (45 DTE, bid/ask), and won in 12 of 14 years. The two years it lost were 2015 and 2022, the flat and falling ones. It's a long-delta position and 2010 to 2023 was a bull market, so the question is how to recognize a bad market before selling one.

I tested five trend readings on the day before entry (naked put vs strangle, annual return on buying power, 45 DTE):

| Reading | Naked put, trend up | Strangle, trend up | Naked put, trend down | Strangle, trend down |
|---|---|---|---|---|
| SPX above 200-day | 49.5% | 17.3% | 146.8% | 98.4% |
| Up over 20 days | 29.0% | 16.0% | 166.7% | 65.8% |
| Within 5% of 52-week high | 41.3% | 9.8% | 134.4% | 89.6% |
| **50-day above 200-day** | **60.4%** | **19.4%** | **79.6%** | **81.0%** |

Short-term weakness is the naked put's best entry, not its worst: after a dip, premiums are fat and markets mostly rebounded. Only the 50/200 cross separates the two: in a death cross the strangle did as well or better (and better in 2019 to 2023: 73.1% vs 43.5%).

OptionsDX starts in 2010, so it has no long bear market. Cboe's put-write indices go back further. With the 50-day below the 200-day:

| Index | 2007-2009, trend down | 2007-2009, trend up | 2010-2023, trend down |
|---|---|---|---|
| PUT (ATM monthly put) | -7.2%/yr, 5th-pct month -13.0% | +48.5%/yr | +15.7%/yr |
| PUTD (30-delta put) | -8.1%/yr, 5th-pct month -15.1% | +13.2%/yr | +19.3%/yr |

In a real bear market, selling puts in a death cross lost money. Over the whole record the death-cross months had about the same return as the rest with twice the bad-month loss. That is the case for the rule.

**Rule:** offer the naked put only when the 50-day is above the 200-day. Missing or stale history (more than 5 days old) counts as not up.

## Evidence 4: the whole rule set, end to end

Same SPX trades, picking what each rule set would have proposed on each entry day. One SPX lot per entry, 50% target, bid/ask fills.

| Rule set | Win % | Annual return on BP | 5th pct | Worst | Max drawdown |
|---|---|---|---|---|---|
| Old: strangle, 45 DTE | 89.3% | 30.1% | -$3,491 | -$82,469 | -$362,841 |
| Strangle, 60 DTE | 90.0% | 46.5% | -$3,782 | -$77,670 | -$435,579 |
| **New: 60 DTE, naked put in uptrend, else strangle** | **97.1%** | **93.1%** | **+$330** | **-$61,132** | **-$131,645** |
| Naked put always, 60 DTE | 98.0% | 85.8% | +$350 | -$61,132 | -$125,463 |

In 2022, the one bear market in the sample, the trend rule earned its place:

| 2022 | Annual return on BP | Worst | Max drawdown |
|---|---|---|---|
| New rule set | 185.6% | -$9,993 | -$12,616 |
| Naked put always | 74.7% | -$34,658 | -$34,658 |

Max drawdown here is on a book that opens a lot every 3 sessions, so 15 to 20 positions overlap. Read it as a comparison, not a forecast; the sizing cap changes the dollars.

## What this does not fix

- **COVID still happens.** The worst naked put trades opened in February 2020 with the trend up. The trend rule doesn't stop a crash; the 5% worst-case sizing cap does.
- **Bull-market sample.** 2010 to 2023 rewarded long delta. The 2007-2009 index check is the only bear-market evidence, and it's index-level, not trade-level.
- **The delta:theta limit was a mentor rule.** Loosening it for the naked put is a deliberate decision to take directional risk in uptrends. It needs Jonathan's sign-off before it ships.

## Evidence 5: put verticals need wide wings

At the old setting (25-delta short, wings 0.75% of spot, about 15 SPX points in 2013) the vertical collected $1 to $3 of credit and the four-sided bid/ask took all of it. I swept wing width and short delta at 60 DTE with the production builder. Return on credit, 50% target:

| Wings (% of spot) | Short delta | Bid/ask fills | Mid fills | Median fill cost | 2010-2018 bid/ask | 2019-2023 bid/ask |
|---|---|---|---|---|---|---|
| 0.75% | 0.25 (old) | -65.1% | 22.2% | 30% | -160.6% | -18.9% |
| 0.75% | 0.16 | -112.0% | 27.2% | 39% | -434.8% | -28.2% |
| 1.5% | 0.16 | -23.2% | 29.6% | 21% | -69.3% | 0.8% |
| 2.5% | 0.16 | 6.0% | 34.6% | 13% | -6.7% | 13.7% |
| 3.5% | 0.16 | 16.7% | 36.3% | 10% | 10.2% | 21.0% |
| **5%** | **0.16** | **23.3%** | **37.5%** | **7%** | **22.1%** | **24.1%** |
| 5% | 0.25 | 11.3% | 21.7% | 6% | 13.0% | 10.1% |

5% wings with a 16-delta short is the first setting that's positive at bid/ask in both halves: 30.1% a year on buying power (average buying power about $11,700 per SPX lot). That ties the old strangle and trails the naked put, so the vertical is a fallback, not the default.

**Fill-cost guard.** Skipping any structure whose natural fill gives up more than 25% of its mid credit lifts the 5% vertical from 23.3% to 26.4% return on credit, and it would have rejected most of the old 0.75% verticals outright. The alert's limit price is still the mid credit; the guard is for orders that can't get near it.

At 5% wings the vertical's delta:theta is about 1:0.28, still outside the mentor's 1:2. It's the same long-delta bet as the naked put, so it gets the same treatment: only in an uptrend, with a 1:0.25 limit. I haven't tested the vertical against the trend separately.

## Reproduce

```
python research/spx-replay/all_strategies.py data/optionsdx/spx --dte 45 60 --trades trades.csv
python research/spx-replay/rules_v2.py trades.csv            # trend readings and the end-to-end table
python research/spx-replay/vertical_sweep.py data/optionsdx/spx  # evidence 5, about 15 minutes
python -m unittest discover -s tests -t .
```

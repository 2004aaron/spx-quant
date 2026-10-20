# Engine calibration: how accurate are the risk numbers? (SPX 2010 to 2023)

Every proposal carries the engine's own estimates: probability of profit, expected value, CVaR 5% and a stress-test worst case. This checks them against what really happened. On each entry day (every 3 sessions) the production builder and risk block ran exactly as in a live scan, on current params at 60 DTE, against that day's OptionsDX SPX chain. Each position was then held to expiry and settled at the close, which is the model's own assumption, with P/L at mid. Script: `research/spx-replay/calibration.py`.

## Results

| | Strangle | Naked put | Put vertical |
|---|---|---|---|
| Entries | 1,135 | 1,135 | 1,133 |
| Predicted win rate | 77.7% | 92.6% | 91.8% |
| Realized win rate | 78.1% | 94.8% | 94.2% |
| Predicted average P/L per lot | $277 | $1,006 | $278 |
| Realized average P/L per lot | $1,164 | $1,279 | $484 |
| Predicted CVaR 5% | -$22,780 | -$16,010 | -$10,217 |
| Realized worst-5% average | -$16,937 | -$12,974 | -$8,384 |
| Losses beyond the stress-test worst case | 23 (2.0%) | 15 (1.3%) | 34 (3.0%) |
| Above-median predicted EV: realized average | $2,185 | $1,788 | $470 |
| Below-median predicted EV: realized average | $142 | $770 | $497 |

## What it says

- **Probability of profit is right on average.** It's within 2.5 points of the realized win rate for all three structures, a little on the low side. It can't tell you which trade will lose, though. Its Brier score equals the score you'd get by always guessing the average (0.171 vs 0.171 for the strangle), because at a fixed delta every trade gets nearly the same POP.
- **Expected value is conservative.** The realized average was 1.3x (naked put) to 4x (strangle) the prediction. The model charges for a -15% crash 0.25 times a year and assumes realized vol 10% below implied; over 2010 to 2023 crashes were rarer and the volatility risk premium was bigger. That's a bull-market sample, so I'd keep the conservative assumptions rather than tune them to it.
- **EV ranks trades well for the naked structures.** Strangles in the top half of predicted EV made $2,185 a lot against $142 for the bottom half; naked puts $1,788 against $770. For verticals it has no ranking power ($470 vs $497).
- **CVaR 5% is conservative too**, by 20 to 35%. The predicted tail was worse than the realized one.
- **The stress-test "worst case" is about a 98th-percentile loss, not a true worst case.** 1 to 3% of trades lost more than it. Those breaches cluster: entries in January to February 2020 (31), March to April and August 2022 (16), and June to July 2011 (10). That's what the 5% worst-case cap sizes against, so on those trades the real loss ran past the cap.

## Limits

- Held to expiry only, because that's what the model predicts. The live engine exits at the 50% profit target, where the realized win rate is higher (about 90% strangle, 98% naked put).
- One lot, mid fills, close settlement, no commissions.
- Bull-market sample; the conservative EV may be right for a sample with 2008 in it.

## Reproduce

```
python research/spx-replay/calibration.py data/optionsdx/spx --csv calibration.csv   # about 10 minutes
```

# Tier B on SPX (OptionsDX)

The September Tier B replay ran on SPY, 2019 to 2026: one bull market, two stress events, 327 trades. This re-runs it on SPX end-of-day chains from OptionsDX, 2010 to 2023, which adds 2011, 2015, 2018 (Volmageddon) and 2022, and takes every exit mark from a real quote instead of a model.

## Get the data

OptionsDX gives SPX end-of-day chains away free, one year per download, behind a free account.

1. optionsdx.com, SPX Option Chains, quote frequency **End of Day**
2. Add each year 2010 to 2023 to the cart and check out ($0)
3. Download the zips from My account, Downloads, into `data/optionsdx/` (ignored by git)

No need to unzip. The script reads zips, folders or single files.

## Run

```
python research/rules-pivot/tier_a.py                 # optional: caches VIX histories for the regime split
python research/spx-replay/tier_b_spx.py data/optionsdx --json docs/results/tier-b-spx.json
```

Defaults come from `config/params.toml`: 16-delta strangle, 45 DTE target inside 30 to 60, one entry every 3 sessions, 1 lot.

## What it reports

- Hold to expiry vs the 50% profit target (the only default exit since the rules pivot)
- Two fill modes: bid/ask (sell the bid, buy the ask) and mid, so execution cost is bracketed
- Concentration: what the worst 5% of trades cost against total gains
- Profit-target results by year, and by the regime read the day before entry when the VIX cache exists

## Limits

- Monthly SPX settles on the Friday open (SOQ); this settles every expiry at the close.
- No commissions. SPX is European, so no early assignment.
- Still one strategy and one lot. Nothing here tests a portfolio.

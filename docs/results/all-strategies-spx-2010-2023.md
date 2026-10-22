# All four strategies on SPX, 2010 to 2023 (OptionsDX)

Every StormGlass builder (strangle, naked put, put vertical, iron condor), replayed on OptionsDX SPX end-of-day chains. Strikes are picked by the production code (`spx_quant.strategies.build`) with today's `params.toml`, so each trade is the one the engine would have built that day. Buying power comes from `spx_quant.margin`. A new 1-lot trade opens every 3 sessions. Exits are the 50% profit target (read on the mid) or expiration, settled at the close. Script: `research/spx-replay/all_strategies.py`. Raw output: [`all-strategies-spx-2010-2023.json`](https://github.com/2004aaron/spx-quant/blob/research/docs/results/all-strategies-spx-2010-2023.json).

Two fill modes bracket execution. **Bid/ask** sells every leg at the bid and buys at the ask, which is the worst realistic case. **Mid** fills at the midpoint, which is the best case.

## Headline: 45 DTE target (current default), 50% profit target

| Strategy | Fills | n | Win % | Return on credit | Annual return on PM buying power | 5th pct | Worst |
|---|---|---|---|---|---|---|---|
| Strangle | bid/ask | 1,149 | 89.3% | 14.9% | 30.1% | -$3,491 | -$82,469 |
| Strangle | mid | 1,149 | 89.3% | 19.4% | 40.4% | -$3,378 | -$82,439 |
| Naked put | bid/ask | 1,149 | 97.7% | 32.2% | 63.6% | +$270 | -$66,372 |
| Naked put | mid | 1,149 | 97.7% | 35.8% | 72.9% | +$380 | -$66,357 |
| Put vertical | bid/ask | 1,148 | 55.1% | -56.6% | -150.6% | -$1,059 | -$5,258 |
| Put vertical | mid | 1,148 | 93.7% | 22.0% | 90.1% | -$834 | -$5,098 |
| Iron condor | bid/ask | 1,094 | 55.3% | -53.4% | -184.2% | -$1,870 | -$7,180 |
| Iron condor | mid | 1,094 | 81.0% | 2.9% | 13.8% | -$1,750 | -$6,920 |

Spread buying power is tiny (about $1,450 a lot against $18,000 to $19,000 for the naked structures), so small dollar moves become large percentages on buying power.

## What it says

- **The naked put is the strongest structure.** It roughly doubles the strangle's return on buying power (63.6% vs 30.1% at bid/ask). It held up in both halves: 67.7% vs 36.3% in 2010–2018, and 59.5% vs 23.9% in 2019–2023. Its 5th-percentile trade is a gain and its worst trade is smaller. By year, it beat the strangle in 12 of 14 years.
- **But it's a directional bet.** The two years it lost to the strangle were 2015 (31.8% vs 37.6%) and 2022 (6.7% vs 23.7%), the flat and falling years. SPX roughly quadrupled from 2010 to 2023, and that tailwind pays a long-delta position. That's exactly the risk the delta:theta limit is there to cap.
- **The engine never proposes it today.** On a real board, the 1:2 delta:theta limit rejects the naked put (1:0.7), the put vertical (1:0.1) and the iron condor (1:1.1). Only the strangle passes. That's why all 13 Alpha proposals were strangles. The limit is a mentor rule, and the data says it costs about half the return.
- **The put vertical works only if you fill near mid.** At mid: 22% return on credit and a 94% win rate. At bid/ask: -57%. The 0.75%-of-spot wing (about 15 SPX points in 2013) collects $1 to $3 of credit, and four bid/ask spreads eat all of it. Wider wings or limit orders at mid would be needed before a vertical is worth proposing.
- **The iron condor doesn't earn its place.** It made 2.9% at mid fills and lost money held to expiry, even at mid. The September Tier A study found the same thing on Cboe's condor index (CNDR). It should come out of the playbook, or be retested with wider wings.
- **60 DTE helps every structure that works.** At 60 DTE with the 50% target and bid/ask fills, the strangle goes from 30.1% to 46.5% and the naked put from 63.6% to 85.8%, both on PM buying power. That matches the strangle-only sweep.

## 60 DTE target, 50% profit target

| Strategy | Fills | Win % | Return on credit | Annual return on PM BP | Worst |
|---|---|---|---|---|---|
| Strangle | bid/ask | 90.0% | 21.9% | 46.5% | -$77,670 |
| Naked put | bid/ask | 98.0% | 40.9% | 85.8% | -$61,132 |
| Put vertical | mid | 93.7% | 21.8% | 73.8% | -$3,015 |
| Iron condor | mid | 81.4% | 5.2% | 21.0% | -$4,510 |

## Limits

- 2010–2023 was a strong bull market. Naked puts and short strangles both benefit, and naked puts more.
- One lot per trade, no sizing cap. In production the 5% worst-case cap would cut naked contracts hard on a $150k account; on the recorded September 28 board, one SPX lot of either naked structure is over the cap.
- OptionsDX has no open interest, so the OI/volume liquidity check is skipped. The spread and minimum-mid checks still apply.
- Close settlement for every expiry; no commissions.

## Reproduce

The scripts and raw data are on the [`research` branch](https://github.com/2004aaron/spx-quant/tree/research).

```
python research/spx-replay/all_strategies.py data/optionsdx/spx --dte 45 60 \
    --json docs/results/all-strategies-spx-2010-2023.json --trades trades.csv
```

About 4 minutes on a laptop.

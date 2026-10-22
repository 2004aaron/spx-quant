# Operations

## Daily schedule (Pacific time, trading days only)

| Job | Time | Command | Why then |
| --- | --- | --- | --- |
| scan | 10:30 | `scan --slot 10:30` | morning scan; quotes are about 15 minutes old |
| scan | 13:25 | `scan --slot 13:25` | end-of-day scan, 10 minutes after the 13:15 SPX options close |

Weekends and NYSE holidays log a `market_closed` scan. A scan that starts more than
30 minutes after its slot says so in its output and logs a `scan_late` event. On the
early-close days (November 27 and December 24, 2026) SPX options stop at 10:15 PT, so
the 13:25 scan answers NO ADVICE (stale).

The scheduled runs live outside this repository, in a private runner, because the log
carries the pilot's account size. Each run starts empty, loads the log, scans and saves
it. `deploy/cloud/logdoc.py` dumps the SQLite log to a SQL file that ends with a sha256
line, and `load` refuses a copy whose checksum doesn't match, so a damaged copy never
replaces the log. The profile is set fresh on every run and is never committed (QR-5).

## Evidence commands

```bash
python -m spx_quant kr a1                    # Oct 5-16 by default
python -m spx_quant kr a2 --plant            # includes the planted-row proof
python -m spx_quant kr a3 > docs/results/a-kr3.md
```

Each prints a markdown table. Commit the output. The exit code is 0 only when the
target is met.

## Account tiers and limits (decided 2026-10-06)

| Tier | Net liq | Margin | Delta:theta default | BP per position | Worst case per position |
|---|---|---|---|---|---|
| starter | under $100,000 | Reg-T only | 1:2 | 8% | 5% |
| standard | $100,000 to $999,999 | Reg-T or portfolio | 1:2 | 8% | 5% |
| large | $1,000,000 and up | Reg-T or portfolio | 1:7 | 8% | 5% |

Pilot profile: $150,000, portfolio margin (standard tier).

- **Delta is SPY-weighted**, the way tastytrade beta-weights a portfolio: one SPX
  share-delta is 10 SPY deltas, one XSP share-delta is 1. The mentor's 1:2 limit only
  makes sense in these units.
- **1:2 under $1M, 1:7 at $1M and up**, from the mentor: 1:2 "is the limit"; with
  millions, "closer to like 1:10, 1:7".
- **Bullish structures in an uptrend.** When the SPX 50-day is above the 200-day the naked
  put gets a 1:0.5 limit and the put vertical 1:0.25 (rules v2,
  [`docs/results/rules-v2.md`](results/rules-v2.md)). Otherwise neither is offered.
- **Portfolio margin needs $100,000** (tastytrade: $125,000 to open, $100,000 to keep),
  so a portfolio profile under $100,000 is rejected with a message to use Reg-T.
- **8% buying power per position** (US-01-AC1): three to six positions fill 25% to 50%
  of net liq.
- **5% worst case per position.** The worst case is an instant 10% index drop with
  volatility up 10 points; six positions at the cap lose at most about 30% in that event.

## Notes

1. **Portfolio margin is a model.** The engine scans tastytrade's published range for
   equity indices (-15% to +10%), not the regulatory floor (-8% to +6%). The broker's
   number can differ.
2. **How A-KR2 reads "checked against the next 10:30 scan".** An end-of-day proposal's
   legs are checked for listing, bids, liquidity and quote age on the next morning's
   board. The credit is checked against the quotes it was built on: one night of theta
   moves a strangle's price by more than its whole bid-ask width, so an overnight credit
   check could never pass.

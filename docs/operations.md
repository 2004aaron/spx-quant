# Operations

## Daily schedule (Pacific time, trading days only)

| Job | Time | Command | Why then |
| --- | --- | --- | --- |
| scan | 10:30 | `scan --slot 10:30` | A-KR1 morning scan; quotes are about 15 minutes old |
| scan | 13:25 | `scan --slot 13:25` | end-of-day scan, 10 minutes after the 13:15 SPX options close |

The diagram's log example shows the second scan at 12:50. That sample is labeled
illustrative, and A-KR2 checks end-of-day proposals against the next morning's
board, which only makes sense for a scan after the close, so the build keeps 13:25.
Change `schedule.slots` and `schedule.eod_slot` together if you want 12:50.

Weekends and NYSE holidays log a `market_closed` scan. A scan that starts more than
30 minutes after its slot says so in its output and logs a `scan_late` event. On the
early-close days (November 27 and December 24, 2026) SPX options stop at 10:15 PT, so
the 13:25 scan answers NO ADVICE (stale).

## Cloud schedule (from October 8, 2026)

Cloud scheduled tasks run the scans so the laptop doesn't have to be on:

| Task | Time (PT) | Steps |
| --- | --- | --- |
| 10:30 scan | weekdays 10:30 | clone `main`, load the log, `scan --slot 10:30`, save the log |
| end-of-day scan | weekdays 13:25 | same with `scan --slot 13:25`, then `kr a1` |

Each run starts in an empty container, so the log lives between runs as a project
document: a SQL dump that ends with a sha256 line. `deploy/cloud/logdoc.py load`
refuses a copy whose checksum doesn't match, so a damaged copy never replaces the log.
The profile ($150,000, portfolio margin) is set fresh on every run and is never
committed (QR-5). The 13:25 run has about 20 minutes of slack: after the 13:15 close
the quotes age past the 30-minute limit around 13:45.

## Setup on one machine

```powershell
python -m spx_quant profile set --net-liq 150000 --margin portfolio --bp-cap 0.08
.\deploy\windows\register_tasks.ps1
```

The PC must be on Pacific time. The script sets WakeToRun so a sleeping laptop wakes
for the slot; a laptop that is shut down still misses it, which is why the scans also
run as cloud tasks.

## Evidence commands

```bash
python -m spx_quant kr a1                    # Oct 5-16 by default
python -m spx_quant kr a2 --plant            # includes the planted-row proof
python -m spx_quant kr a3 > docs/results/a-kr3.md
```

Each prints a markdown table. Commit the output. The exit code is 0 only when the
target is met.

## Cutting over from the shadow log

The cloud scheduled task "SPX Quant shadow log" still runs `shadow-runner.py` once a
day at 2:30 PM PT and keeps its own JSONL log. It opens one lot every day regardless
of the gate, which is useful for measuring the gate and useless for A-KR1. Keep it
running until the scheduled `scan` jobs have logged a clean week, then pause it.

## Account tiers and limits (decided 2026-10-06)

These were waiting on the mentor. I set them myself so the Alpha window runs on real
defaults; every one is still tagged unvalidated and Jonathan can override any of them.

| Tier | Net liq | Margin | Delta:theta default | BP per position | Worst case per position |
|---|---|---|---|---|---|
| starter | under $100,000 | Reg-T only | 1:2 | 8% | 5% |
| standard | $100,000 to $999,999 | Reg-T or portfolio | 1:2 | 8% | 5% |
| large | $1,000,000 and up | Reg-T or portfolio | 1:7 | 8% | 5% |

Pilot profile: $150,000, portfolio margin (standard tier).

- **Delta is SPY-weighted.** Delta in the ratio is counted the way tastytrade
  beta-weights a portfolio: SPY deltas, the dollar P/L of a $1 move in SPY (SPY taken
  as SPX/10, beta 1). One XSP lot of a 0.16-delta put is about 16 SPY deltas; the same
  SPX lot is about 160. Before this the engine counted SPX-equivalent shares, which is
  ten times smaller. Reason: the mentor's numbers only make sense in SPY units. At
  1:2 in SPX shares a 1% index move would cost about 38 days of theta, which nobody
  selling premium for theta would call "theta as the primary income driver". At 1:2 in
  SPY deltas the same move costs about 4 days. tastylive uses the same unit and the
  same number: beta-weighted deltas, and a delta/theta ratio of about 0.5 (1:2) as the
  target for a short-delta book.
- **Delta:theta 1:2 under $1M, 1:7 at $1M and up.** From the August call: 1:2 "is the
  limit, I would not be more directional than that"; with millions 1:2 is "too much",
  so "we'll try to get closer to like 1:10, 1:7". 1:7 is the edge of his normal range
  for large accounts. On a day he wants to lean directional he said 1:4 or 1:5 is fine;
  that is a `--dt-limit 4` override, not the default.
- **Consequence:** a lone 16-delta naked put is about 1:0.7, so it is refused as too
  directional at every tier. Strangles, which the mentor called "our bread and
  butter", pass easily (about 1:59 on the September 28 close). Naked puts come back
  only with a looser `--dt-limit`.
- **Portfolio margin needs $100,000.** tastytrade requires $125,000 to open portfolio
  margin and $100,000 to keep it, so a portfolio profile under $100,000 is rejected
  with a message to use Reg-T. The starter tier exists to say that plainly. At an 8%
  cap, one XSP strangle under Reg-T (about $8,400 to $9,000 of buying power) does not
  fit until about $105,000 to $113,000 of net liq, so a starter account will mostly see
  stand-downs.
- **8% buying power per position (unchanged).** It is the value in US-01-AC1. At 8%,
  three to six positions fill 25% to 50% of net liq, the total buying-power range
  tastylive commonly cites (I have not pinned a page for that range yet).
- **5% worst case per position (was 10%).** The worst case is an instant 10% index
  drop with volatility up 10 points. At 10% per position, six open positions could
  lose 60% in that one event; at 5% the same book loses at most about 30%. On the
  September 28 close the pilot's strangle uses $3,935 of a $7,500 limit, so the change
  does not cut the pilot's size; it binds when buying power is loose (a 20% cap, or the
  elevated-volatility rows in A-KR3).
- **A-KR3 sizes moved** from $25k / $75k / $150k / $1.5M to $100k / $150k / $500k /
  $1.5M, because portfolio margin under $100,000 is no longer a valid profile. The
  matrix now runs on tier defaults instead of a hard-coded 1:2.

## Open decisions this build exposed

1. **Portfolio-margin calibration.** The engine's scan range is now tastytrade's
   published minimum for equity indices (-15% to +10%), not the regulatory floor
   (-8% to +6%). It is still a model. To match the broker exactly:
   `python -m spx_quant margin-check` prints the latest proposal as a ticket; enter it
   in tastytrade without sending, then run
   `python -m spx_quant margin-check --broker-bp <ticket BP> --apply`. That writes
   `margin.pm_house_multiplier` = broker / engine and records the check in its
   provenance. Repeat on a strangle once one is proposed.
2. **How A-KR2 reads "checked against the next 10:30 scan".** The script checks an
   end-of-day proposal's legs for listing, bids, liquidity and quote age on the next
   morning's board. The credit is checked against the quotes it was built on, not the
   next morning's: one night of theta moves a strangle's price by more than its whole
   bid-ask width, so an overnight credit check could never pass. Worth one sentence in
   the proposal's change log.

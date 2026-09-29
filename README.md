# SPX Quant

A regime-aware advisory engine for self-directed index option sellers (SPX / XSP).
It reads delayed market data, classifies the volatility regime from the VIX term
structure, builds and sizes candidate short-premium positions against your account
profile, and either sends a specific proposal with its risk numbers or says
**STAND DOWN** with the reasons. It never places an order.

Westmont College CS 195 Senior Seminar capstone, Fall 2026. Student: Aaron Wu
(`aawu`, GitHub `2004aaron`). Instructor: Mike Ryu. Mentor: Jonathan Hong.

## Current state (v0.4: Alpha and Beta stories built)

Story IDs follow the final proposal (September 27, 2026). Every acceptance criterion
has a test; the map is in [`docs/story-map.md`](docs/story-map.md).

| Story | What it does | Module |
| --- | --- | --- |
| US-01 account profile | size, margin type, BP cap, delta:theta limit, notification address; bad input keeps the old profile | `profile.py` |
| US-02 regime | contango / flat / backwardation and a volatility bucket, with the VIX values and a timestamp; names a missing point | `regime.py` |
| US-03 sized proposal | four builders (strangle, naked put, put vertical, iron condor) on SPX, falling back to XSP when SPX cannot fit; Reg-T and portfolio margin; inclusive cap; ranked by expected annual return on buying power | `strategies.py`, `margin.py`, `sizing.py`, `engine.py` |
| US-04 stand-down | floor 13, ceiling 28, backwardation; reasons logged | `regime.py`, `engine.py` |
| US-05 risk block | probability of profit, expected value, CVaR 5% / 1% (worst case), breakevens, stress rows, implied crash rate, stated assumptions; refuses to default a missing assumption | `analytics.py` |
| US-06 data check | one fetch per scan, checked for shape, size and quote age before use | `data/cboe.py` |
| US-07 notifications | email (SMTP/TLS) or Discord webhook, retries, no repeat for unchanged conditions, failures recorded | `notify.py` |
| US-08 log | SQLite, six append-only tables (scan, alert, delivery, mark, feedback, event), query by date | `store.py`, `pipeline.py` |
| US-09 daily marks | values every logged proposal at the close as if it had been opened; settles at expiration | `mark.py` |
| KR scripts | A-KR1, A-KR2 (with planted bad rows), A-KR3 (24 cases), B-KR1 to B-KR3 | `kr.py` |

Not built yet (RC): reply capture (US-10), weekly report (US-11), failure digest (US-12),
remaining-buying-power sizing (US-13), stacked vs staggered books (US-14). The
`feedback` table and the `event` rows they need already exist.

## Run it

Python 3.11 or newer. No third-party packages, no install step.

```bash
git clone https://github.com/2004aaron/spx-quant.git
cd spx-quant
python -m unittest discover -s tests -t . -v        # 133 tests, about 15 seconds

python -m spx_quant profile set --net-liq 150000 --margin portfolio --bp-cap 0.08 --dt-limit 2
python -m spx_quant profile show

python -m spx_quant probe             # feed check against the live Cboe board
python -m spx_quant regime            # VIX term structure -> regime and gate
python -m spx_quant scan --no-send    # full scan, logged to ~/.spx-quant/quant.db
python -m spx_quant log --from 2026-10-05
python -m spx_quant mark              # after the close
python -m spx_quant kr a3             # A-KR3 sizing matrix
```

Global options go before the command: `--profile PATH`, `--db PATH`, `--params PATH`.
Each pilot user gets their own profile and database.

Outside market hours the live feed is stale and `scan` answers NO ADVICE. To see a
full proposal any time, replay the recorded September 28 close:

```bash
python -m spx_quant scan --no-send --slot 13:25 \
  --replay tests/data/cboe-2026-09-28-close.json.gz --now 2026-09-28T20:25:00+00:00
```

The output is in [`docs/sample-alert.txt`](docs/sample-alert.txt). Scheduling, email and
Discord setup, and the Beta host are in [`docs/operations.md`](docs/operations.md).

## Layout

```
spx_quant/
  __main__.py      CLI
  profile.py       account profile                                US-01
  regime.py        classifier and stand-down gate                 US-02, US-04
  data/cboe.py     live feed, replay, freshness check             US-06
  strategies.py    four structure builders                        US-03
  margin.py        Reg-T and portfolio-margin buying power        US-03
  sizing.py        inclusive BP cap, delta:theta guardrail        US-01, US-03
  analytics.py     risk block                                     US-05
  engine.py        one scan, pure: returns a ScanResult
  alert.py         alert id, fingerprint, plain-text message      QR-6, B-KR3
  store.py         append-only SQLite log                         US-08
  pipeline.py      scan -> log -> send                            US-07, US-08
  notify.py        email and Discord delivery                     US-07
  mark.py          daily marking job                              US-09
  kr.py            key-result checks                              section 6
  synthetic.py     synthetic boards for tests and A-KR3
  clock.py         Eastern/Pacific time and the NYSE calendar without tzdata
config/params.toml every parameter with a validation tag and a source
deploy/            Windows Task Scheduler script, crontab for the Beta host
docs/              build notes, backtest findings, story map, operations, KR results
tests/             unittest suite; tests/data holds the recorded session
```

## Scope and disclaimer

Advisory only. No broker access, no order execution, two pilot users. Outputs are
model estimates with tagged assumptions, not investment advice. The historical
evidence for regime timing is negative (see `docs/backtest-findings.md`) and most
parameters are still tagged unvalidated.

## License

MIT, see [LICENSE](LICENSE).

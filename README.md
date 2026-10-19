# StormGlass

Sailors read a storm glass before leaving port. StormGlass reads the market's weather
before you sell index options.

It's a regime-aware advisory engine for self-directed SPX / XSP option sellers. It
reads delayed Cboe data, classifies the volatility regime from the VIX term structure,
builds and sizes candidate short-premium positions against your account profile, and
either gives you a specific proposal with its risk numbers or says **STAND DOWN** with
the reasons. It never places an order.

Westmont College CS 195 Senior Seminar capstone, Fall 2026. Student: Aaron Wu
(`aawu`, GitHub `2004aaron`). Instructor: Mike Ryu. Mentor: Jonathan Hong.

The project started as SPX Quant. The Python package and the commands keep that
working name (`python -m spx_quant`), so existing scripts and schedules still run.

## Alpha release (v0.6.1-alpha, October 19, 2026)

Alpha covers US-01 to US-06 from the final proposal (September 27, 2026), plus the
scan log and the scripts that check the Alpha key results. v0.6.1 adds the October 19
rules pivot (an inverted VIX curve is now information, not a stand-down) and the final
Alpha key results. Every acceptance criterion
has a test; the map is in [`docs/story-map.md`](docs/story-map.md).

| Story | What it does | Module |
| --- | --- | --- |
| US-01 account profile | size, margin type, BP cap, delta:theta limit, worst-case limit; account tiers; bad input keeps the old profile | `profile.py` |
| US-02 regime | contango / flat / backwardation and a volatility bucket, with the VIX values and a timestamp; names a missing point | `regime.py` |
| US-03 sized proposal | four builders (strangle, naked put, put vertical, iron condor) on SPX, falling back to XSP when SPX can't fit; Reg-T and portfolio margin; inclusive cap; contracts cut so the stress-test worst case stays within the profile's limit (default 5% of net liq); account tiers set the delta:theta default (1:2 under $1M, 1:7 above, in SPY-weighted deltas); ranked by expected annual return on buying power | `strategies.py`, `margin.py`, `sizing.py`, `engine.py` |
| US-04 stand-down | floor 13 and ceiling 28 by default (`gate.stand_down_on`); backwardation shown as information since the [2026-10-19 rules pivot](docs/results/rules-pivot.md); reasons logged | `regime.py`, `engine.py` |
| US-05 risk block | probability of profit, expected value, worst case (index -10%, volatility +10 points), CVaR 5% / 1%, breakevens, stress rows, implied crash rate, stated assumptions; refuses to default a missing assumption | `analytics.py` |
| US-06 data check | one fetch per scan, checked for shape, size and quote age before use; NO ADVICE on stale or incomplete data | `data/cboe.py` |
| Scan log | every scheduled scan and its result, with the quotes behind it, in append-only SQLite | `store.py`, `pipeline.py` |
| Alpha KR scripts | A-KR1 (both daily scans logged), A-KR2 (entry check, with planted bad rows), A-KR3 (24-case sizing matrix) | `kr.py` |

### Alpha key results (October 5 to 16)

| Key result | Result | Band | Output |
| --- | --- | --- | --- |
| A-KR1 both daily scans complete | 7 of 10 trading days | D | [`docs/results/a-kr1.md`](docs/results/a-kr1.md) |
| A-KR2 proposals that fail an entry check | 0 of 13; 8 of 8 planted bad rows caught | A | [`docs/results/a-kr2.md`](docs/results/a-kr2.md) |
| A-KR3 sizing matrix | 24 cases, 0 violations | A | [`docs/results/a-kr3.md`](docs/results/a-kr3.md) |

Bands come from the grading table in the final proposal. A-KR1 is missing October 5 to 7,
before the cloud schedule started. October 16 counts on the end-of-day scan from the second log;
[`docs/results/a-kr1.md`](docs/results/a-kr1.md) says how the two logs were combined.

## Beta work on main (from October 19)

With Alpha released, the Beta and RC stories are back on `main` for the Beta window
(October 30 to November 15). They were built in v0.5 and held back from the Alpha release.

| Story | What it does | Module |
| --- | --- | --- |
| US-07 alerts | each scan queues one plain-text message in the log; Gmail (through the scheduled run) or Discord sends it; delivery recorded with retries | `notify.py`, `alert.py` |
| US-08 append-only log | scan, alert, delivery, mark, feedback and event tables; updates and deletes refused | `store.py` |
| US-09 daily marks | every open proposal marked at the closing quotes; settlement at expiration | `marks.py` |
| US-10 decisions | accepted, declined, modified N or closed, from the CLI or an email reply | `decisions.py` |
| US-11, US-12 weekly report | advisor book vs your book, predicted vs realized worst case, failures and anomalies | `report.py` |
| US-13 remaining buying power (stretch) | sizes against buying power left after open positions | `sizing.py` |
| Beta and RC KR scripts | B-KR1 to B-KR3, RC-KR1 to RC-KR3, S-KR1 | `kr.py` |

## Run it

Python 3.11 or newer. No third-party packages, no install step.

```bash
git clone https://github.com/2004aaron/spx-quant.git
cd spx-quant
python -m unittest discover -s tests -t . -v        # 192 tests, about 15 seconds

python -m spx_quant profile set --net-liq 150000 --margin portfolio --bp-cap 0.08 --max-worst-case 0.05
python -m spx_quant profile show

python -m spx_quant probe             # feed check against the live Cboe board
python -m spx_quant regime            # VIX term structure -> regime and gate
python -m spx_quant scan              # full scan, logged to ~/.spx-quant/quant.db
python -m spx_quant log --from 2026-10-05
python -m spx_quant kr a1             # A-KR1: both scans on every trading day, Oct 5-16
python -m spx_quant kr a2 --plant     # A-KR2: entry check, with the planted-row proof
python -m spx_quant kr a3             # A-KR3: sizing matrix
python -m spx_quant margin-check      # compare engine buying power with one broker ticket
```

Global options go before the command: `--profile PATH`, `--db PATH`, `--params PATH`.
Each user gets their own profile and database.

Outside market hours the live feed is stale and `scan` answers NO ADVICE. To see a
full proposal any time, replay the recorded September 28 close:

```bash
python -m spx_quant scan --slot 13:25 \
  --replay tests/data/cboe-2026-09-28-close.json.gz --now 2026-09-28T20:25:00+00:00
```

The output is in [`docs/sample-alert.txt`](docs/sample-alert.txt). Scheduling and the
evidence commands are in [`docs/operations.md`](docs/operations.md).

## Layout

```
spx_quant/
  __main__.py      CLI
  profile.py       account profile                                US-01
  regime.py        classifier and stand-down gate                 US-02, US-04
  data/cboe.py     live feed, replay, freshness check             US-06
  strategies.py    four structure builders                        US-03
  margin.py        Reg-T and portfolio-margin buying power        US-03
  calibrate.py     margin-check: engine vs broker buying power    US-03
  sizing.py        inclusive BP cap, delta:theta guardrail        US-01, US-03
  analytics.py     risk block                                     US-05
  engine.py        one scan, pure: returns a ScanResult
  alert.py         alert id and plain-text output                 US-03 to US-06, QR-6
  store.py         append-only SQLite scan log                    A-KR1, A-KR2
  pipeline.py      scan -> log
  kr.py            Alpha key-result checks                        section 6
  synthetic.py     synthetic boards for tests and A-KR3
  clock.py         Eastern/Pacific time and the NYSE calendar without tzdata
config/params.toml every parameter with a validation tag and a source
deploy/            Windows Task Scheduler script, cloud log carrier
docs/              build notes, backtest findings, story map, operations, KR results
tests/             unittest suite; tests/data holds the recorded session
```

## Scope and disclaimer

Advisory only. No broker access, no order execution. Outputs are model estimates with
tagged assumptions, not investment advice. The historical evidence for regime timing
is negative (see `docs/backtest-findings.md`) and most parameters are still tagged
unvalidated.

## License

MIT, see [LICENSE](LICENSE).

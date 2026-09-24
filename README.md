# SPX Quant

A regime-aware advisory engine for self-directed index option sellers (SPX / XSP).
It reads delayed market data, classifies the volatility regime from the VIX term
structure, builds and sizes candidate short-premium positions, and either sends a
specific proposal with its risk numbers or says **STAND DOWN** with the reasons.
It never places an order.

Westmont College CS 195 Senior Seminar capstone, Fall 2026. Student: Aaron Wu
(`aawu`, GitHub `2004aaron`). Instructor: Mike Ryu.

## Current state (v0.3, Sprint 1)

This is the first potentially shippable increment: the pieces of the pipeline that
the Alpha stories US-01, US-02 and US-11 depend on, rebuilt as a clean package
with tests. Everything runs on the Python standard library; no install is needed.

| Area | Module | Status |
| --- | --- | --- |
| Account profile: size, margin type, caps, validation, persistence (US-01) | `spx_quant/profile.py` | working, tested |
| Regime classifier from VIX9D / VIX / VIX3M, `unknown` on missing input (US-02) | `spx_quant/regime.py` | working, tested |
| Alpha stand-down gate: backwardation, crushed, panic (US-04) | `spx_quant/regime.py` | working, tested; the backwardation rule is tagged *tested, not supported* |
| Feed probe: shape drift + staleness, refuses stale data (US-11) | `spx_quant/data/cboe.py` | working, tested on recorded payloads |
| Black-Scholes price, greeks, implied vol | `spx_quant/greeks.py` | working, tested |
| Delta-matched short strangle with liquidity prefilter and DTE snapping (US-03, partial) | `spx_quant/strategies.py` | candidate selection only; sizing, risk block and logging are Sprint 2 |
| Tagged parameters: every value carries a validation tag and a source (US-12) | `config/params.toml`, `spx_quant/params.py` | working, tested; untagged parameter fails load |
| Sizing and delta:theta guardrail (US-05), risk block (US-06), notifications (US-07), append-only log and marks (US-08, US-09), backtest harness (US-10) | not in this repo yet | see the Project board |

What the earlier prototype learned, and why the design looks like this, is in
[`docs/engine-build-notes.md`](docs/engine-build-notes.md). The first validation
pass against nineteen years of Cboe strategy-index history is in
[`docs/backtest-findings.md`](docs/backtest-findings.md); its headline result is
that the regime gate as first implemented shows no edge, which is why refusal,
sizing and auditability are the product rather than timing.

## Run it

Python 3.11 or newer. No third-party packages.

```bash
git clone https://github.com/2004aaron/spx-quant.git
cd spx-quant

python -m unittest discover -s tests -v          # 20 tests, under a second

python -m spx_quant profile set --net-liq 150000 --margin portfolio
python -m spx_quant profile show
python -m spx_quant profile set --net-liq -5 --margin portfolio   # rejected, previous profile kept

python -m spx_quant regime      # live VIX term structure -> regime and gate decision
python -m spx_quant probe       # feed health: shape, freshness, strikes parsed
python -m spx_quant scan        # probe -> regime -> gate -> candidate strangle
```

`regime`, `probe` and `scan` hit Cboe's public delayed-quote CDN (about 15 minutes
behind, no account needed). Outside regular trading hours the probe reports the
quotes as stale and `scan` refuses to advise; that is the intended behaviour of
QR-1, not a bug.

Example output on a trading day:

```
probe: OK  latency 940 ms  strikes parsed 30470
  ok   shape: data.options present (30470 rows)
  ok   freshness: quotes 16 min old
SPX 6,512.40  asof 2026-09-23 17:45 UTC  (cboe (delayed ~15 min))
regime: contango / normal  slope=+0.121  VIX9D=15.10 VIX=16.30 VIX3M=18.27 VIX6M=19.02
candidate: short strangle 2026-11-06 (44 DTE)  6000P (-0.16) / 6925C (+0.16)  credit $3,410  net delta +0.3
Parameters: 3 validated, 10 unvalidated, 1 unvalidated: partially supported, 1 unvalidated: tested, not supported
sizing, risk block and logging are not implemented yet (US-05, US-06, US-08)
```

## Layout

```
spx_quant/
  __main__.py      CLI (profile, probe, regime, scan)
  profile.py       account profile and validation           US-01
  regime.py        term-structure classifier and gate        US-02, US-04
  params.py        tagged parameter loader                   US-12
  greeks.py        Black-Scholes, stdlib math only
  strategies.py    delta-matched strangle builder            US-03 (partial)
  data/cboe.py     Cboe delayed-quote source and probe       US-11
config/params.toml every parameter with tag and source
tests/             unittest suite; CI runs it on every push
docs/              build notes and backtest findings from the prototype
```

## Roadmap

Repository milestones: **Alpha** October 19, **Beta** November 16, **RC** December 9,
2026. Sprint work is tracked on the GitHub Project board linked from the
repository, one issue per story with size, estimate, priority and dates.

The full proposal (user stories US-01 to US-19, quality requirements, OKRs and the
evidence behind each parameter) lives in the course deliverables index under
`students/aawu/`.

## Scope and disclaimer

Advisory only. No broker write access, no order execution, single user. Outputs are
model estimates with stated, tagged assumptions; they are not investment advice.
The historical evidence for regime timing is negative and the forward record is
short.

## License

MIT, see [LICENSE](LICENSE).

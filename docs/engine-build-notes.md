# Prototype build notes (August 2026)

Notes from the v0.2 prototype that preceded this repository. The prototype was
delivered as a zip and is not itself in version control; this repository is the
clean rebuild, one story at a time. Kept here because the parameter tags in
`config/params.toml` cite these findings.

## Architecture of the prototype

VIX term structure -> regime classifier -> playbook grid -> strategy builders ->
filters -> delta:theta and buying-power sizing -> EV and risk analytics -> ranked
alert (text / markdown / JSON). The engine depended on a `MarketDataSource`
protocol so swapping providers touched one file.

## Live data

`--source cboe` pulled the real SPX/XSP chain (with exchange IV and greeks) and the
full VIX term structure from Cboe's public delayed-quote CDN. Verified against live
market data, no broker account needed, about 15 minutes delayed. The endpoint is
undocumented and its shape can drift, so a probe runs before any number is trusted.

Two things that made live data work and are easy to get wrong:

- DTE snapping. Config asks for 30 DTE; the board lists 28 and 31. Exact matching
  returns an empty chain and the engine looks broken when it is merely literal.
- Liquidity prefiltering. Selecting the exact 16-delta strike and then checking
  liquidity is backwards: on a dense board the 16-delta strike is often a thin odd
  strike next to a heavily traded round one. Filter first, then select by delta.
  Accept open interest or volume, since delayed feeds carry previous-session OI.

## Five findings that changed the design

1. Capital adequacy is the binding constraint, not strategy selection. One SPX 30d
   strangle is about $33k of buying power under portfolio margin and $120k+ under
   Reg-T. A $100k account cannot sell SPX naked inside any sane per-position cap,
   so the engine supports XSP (same index, one-tenth notional, same Section 1256
   treatment). Open question for the mentor: what account size and margin type
   is the real target?
2. "As delta neutral as possible" means selling matching deltas on both sides.
   The common 16-delta put / 10-delta call build is deliberately net long delta.
   Delta-matched is the default.
3. Delta:theta needs an explicit unit convention: delta in share-equivalents,
   theta in dollars per day. Tier limits: small accounts at most 1:10 neutral and
   1:2 directional; large accounts 1:15 and 1:7.
4. The original composite score was meaningless (units of nothing, strictly
   positive, could never say "do not do this"). Replaced with expected annualized
   return on buying power plus POP, EV, CVaR 5% / 1%, breakevens and a stress row.
5. EV depends entirely on two uncalibrated knobs (volatility-risk-premium haircut
   and annual crash probability). Set crash probability to zero and the model mints
   free money out of skew. A test asserts exactly this trap. What the model can
   answer without those knobs is the implied crash frequency that sets EV to zero.

## Regime behaviour of the prototype (verified by sweep)

- contango + normal or elevated -> action, size scales with vol
- contango + crushed or panic -> stand down
- backwardation -> stand down at every vol level ("do not get short vega too soon")

The backtest in `backtest-findings.md` later contradicted the backwardation rule.

## Not built in the prototype

Position tracking and P/L, enforcement of management rules, a backtest harness,
the tastytrade DXLink adapter, notifications.

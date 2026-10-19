Output of `python -m spx_quant kr a2 --plant` on v0.6-alpha, run October 19, 2026 over the scan log written by the scheduled 10:30 and end-of-day cloud scans (13 scans, October 8 to 16; dump sha256 `610d3c7cad22c8c70bbc446bb5a9721deb0fc2c3e66ec88a1e6263649539739f`). The log itself is not committed: every row carries the pilot account profile (QR-5).

### A-KR2 proposals that fail an entry check, 2026-10-05 to 2026-10-16

| alert | slot | bp_cap | delta_theta | worst_case | bids | liquidity | fresh | credit |
|---|---|---|---|---|---|---|---|---|
| 2026-10-08-2026-11-20 | 10:30 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-08-2026-11-20-2 | 13:25 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-09-2026-11-20 | 10:30 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-09-2026-11-20-2 | 13:25 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-12-2026-11-27 | 13:25 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-13-2026-11-27 | 10:30 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-13-2026-11-27-2 | 13:25 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-14-2026-11-27 | 10:30 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-14-2026-11-27-2 | 13:25 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-15-2026-11-30 | 10:30 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-15-2026-11-30-2 | 13:25 | ok | ok | ok | ok | ok | ok | ok |
| 2026-10-16-2026-11-30 | 10:30 | ok | ok | ok | ok | ok | ok | ok |

**0 of 12 proposals fail a check**; 0 pending the next morning's scan (target 0 failures across at least 10).

#### Planted rows (in a copy of the log; the real log is untouched)

| planted alert | check | result | detail |
|---|---|---|---|
| PLANT-bp_cap | bp_cap | caught | FAIL: $12,000.01 > $12,000.00 |
| PLANT-delta_theta | delta_theta | caught | FAIL: delta 80.0 vs theta 150.0 at 1:2 |
| PLANT-bids | bids | caught | FAIL: a leg has no bid (at proposal) |
| PLANT-liquidity | liquidity | caught | FAIL: a leg fails the liquidity filter (at proposal) |
| PLANT-fresh | fresh | caught | FAIL: quotes 31.0 min old (at proposal) |
| PLANT-credit | credit | caught | FAIL: credit $3,600.00 outside $3,400.00 to $3,520.00 |
| PLANT-worst_case | worst_case | caught | FAIL: worst case -$15,000.02 beyond the $15,000.00 limit |
| PLANT-next_morning | bids | caught | FAIL: a leg has no bid (10:30 scan on 2026-10-06) |

**8 of 8 planted rows caught.**

Notes:

- 12 proposals, all XSP strangles. Three re-propose the position from the scan before (`NO CHANGE`), at that scan's own quotes and credit; each is checked on its own quotes.
- End-of-day proposals are checked on the next 10:30 scan's quotes (`leg_quotes` in that scan). The last proposal in the window is the October 16 10:30 one, so nothing is pending.
- The second log from October 12 has 7 proposals and 1 failure: its October 13 10:30 scan has no quotes for the October 12 end-of-day proposal. This file scores the one log above.

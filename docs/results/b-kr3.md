Output of `python -m spx_quant kr b3` on v0.7-beta, run November 16, 2026 over the pilot's scan log from the scheduled runner ([stormglass-ops](../operations.md), exported after the November 16 10:30 scan: 41 scans, October 8 to November 16; dump sha256 `81fb3ef07356afa555eab08f5503c7c49c992a46ec6789848fb885cc0582167c`). The log itself is not committed: every row carries the pilot account profile (QR-5).

### B-KR3 alerts carrying quotes, data timestamp and output timestamp, 2026-10-30 to 2026-11-13

Proposals must also name the strategy and carry the trend line (SPX 50-day and 200-day averages with the close date, or the reason the trend is unknown).

| alert | kind | fields |
|---|---|---|
| 2026-10-30-2026-12-31 | proposal | complete |
| 2026-11-02-2026-12-31 | proposal | complete |
| 2026-11-02-2026-12-31-2 | proposal | complete |
| 2026-11-03-2026-12-31 | proposal | complete |
| 2026-11-03-2026-12-31-2 | proposal | complete |
| 2026-11-04-2026-12-31 | proposal | complete |
| 2026-11-04-2026-12-31-2 | proposal | complete |
| 2026-11-05-2026-12-31 | proposal | complete |
| 2026-11-05-standdown | stand_down | complete |
| 2026-11-06-2027-01-08 | proposal | complete |
| 2026-11-06-2027-01-08-2 | proposal | complete |
| 2026-11-09-2027-01-08 | proposal | complete |
| 2026-11-09-2027-01-08-2 | proposal | complete |
| 2026-11-10-2027-01-08 | proposal | complete |
| 2026-11-10-2027-01-08-2 | proposal | complete |
| 2026-11-11-2027-01-08 | proposal | complete |
| 2026-11-11-2027-01-08-2 | proposal | complete |
| 2026-11-12-2027-01-08 | proposal | complete |
| 2026-11-12-2027-01-08-2 | proposal | complete |
| 2026-11-13-2027-01-15 | proposal | complete |
| 2026-11-13-2027-01-15-2 | proposal | complete |

**21 of 21 complete (100%)** (target 100%; grading band A).

Notes:

- 20 proposals and 1 stand-down. Repeats go out as short NO CHANGE messages; they still carry the quotes, the trend line and both timestamps, and are checked the same way.
- The check reads the plain-text body, which is the record. The HTML card added November 12 is built from the same fields.

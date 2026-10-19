Output of `python -m spx_quant kr a1` on v0.6-alpha, run October 19, 2026 over the scan log written by the scheduled 10:30 and end-of-day cloud scans (15 scans, October 8 to 19; dump sha256 `829c745ab5baa5a22bc44af37392e1fe5bb016ddaafa9909dea169c10df2711e`). The log itself is not committed: every row carries the pilot account profile (QR-5).

This log is the primary log (13 scans, sha256 `610d3c7cad22c8c70bbc446bb5a9721deb0fc2c3e66ec88a1e6263649539739f`) plus two scans copied unchanged from the second log the duplicate scheduled tasks kept (sha256 `533bd4123d20385c70d2263bfdef1a8ad701474334a8a5ca520ec1b33605177d`): the October 16 13:25 scan, which the primary task missed because it could not load its log, and the October 19 10:30 scan, whose quotes the October 16 end-of-day proposal is checked against. No row in either log was edited.

### A-KR1 complete proposal or stand-down at every scheduled scan, 2026-10-05 to 2026-10-16

| date | 10:30 PT | 13:25 PT | qualifies |
|---|---|---|---|
| 2026-10-05 | no | no | no |
| 2026-10-06 | no | no | no |
| 2026-10-07 | no | no | no |
| 2026-10-08 | yes | yes | **yes** |
| 2026-10-09 | yes | yes | **yes** |
| 2026-10-12 | yes | yes | **yes** |
| 2026-10-13 | yes | yes | **yes** |
| 2026-10-14 | yes | yes | **yes** |
| 2026-10-15 | yes | yes | **yes** |
| 2026-10-16 | yes | yes | **yes** |

**7 of 10 trading days qualify** (target 10 of 10).

Notes:

- October 5 to 7 have no scans: the cloud schedule started October 8.
- October 16 counts on the second log's 13:25 scan. Without it the primary log alone scores 6 of 10. Both are in the D band (6 to 7).

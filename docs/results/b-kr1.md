Output of `python -m spx_quant kr b1` on v0.7-beta, run November 16, 2026 over the pilot's scan log from the scheduled runner ([stormglass-ops](../operations.md), exported after the November 16 10:30 scan: 41 scans, October 8 to November 16; dump sha256 `81fb3ef07356afa555eab08f5503c7c49c992a46ec6789848fb885cc0582167c`). The log itself is not committed: every row carries the pilot account profile (QR-5).

### B-KR1 delivered within 5 minutes of scan completion, 2026-10-30 to 2026-11-15

| alert | channel | minutes | on time |
|---|---|---|---|
| 2026-10-30-2026-12-31 | email | 0.01 | yes |
| 2026-11-02-2026-12-31 | email | 0.02 | yes |
| 2026-11-02-2026-12-31-2 | email | 0.02 | yes |
| 2026-11-03-2026-12-31 | email | 0.02 | yes |
| 2026-11-03-2026-12-31-2 | email | 0.02 | yes |
| 2026-11-04-2026-12-31 | email | 0.02 | yes |
| 2026-11-04-2026-12-31-2 | email | 0.02 | yes |
| 2026-11-05-2026-12-31 | email | 0.02 | yes |
| 2026-11-05-standdown | email | 0.01 | yes |
| 2026-11-06-2027-01-08 | email | 0.02 | yes |
| 2026-11-06-2027-01-08-2 | email | 0.02 | yes |
| 2026-11-09-2027-01-08 | email | 0.05 | yes |
| 2026-11-09-2027-01-08-2 | email | 0.01 | yes |
| 2026-11-10-2027-01-08 | email | 0.02 | yes |
| 2026-11-10-2027-01-08-2 | email | 0.01 | yes |
| 2026-11-11-2027-01-08 | email | 0.03 | yes |
| 2026-11-11-2027-01-08-2 | email | 0.02 | yes |
| 2026-11-12-2027-01-08 | email | 0.02 | yes |
| 2026-11-12-2027-01-08-2 | email | 0.02 | yes |
| 2026-11-13-2027-01-15 | email | 0.02 | yes |
| 2026-11-13-2027-01-15-2 | email | 0.02 | yes |

**21 of 21 on time (100%)** (target 95%; grading band A, A is 90%+).

Notes:

- "Delivered" means Gmail's SMTP server accepted the message. The minutes are the time from the scan finishing to that acceptance.
- Counts the pilot's alert emails only (proposal, NO CHANGE, stand-down, no advice). The weekly report, the daily paper P/L email and the Monday outlook are not scan alerts and are left out, as the KR says.
- The window ends November 15. November 14 and 15 were a weekend, so the last alerts are from November 13.

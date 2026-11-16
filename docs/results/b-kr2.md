Output of `python -m spx_quant kr b2` on v0.7-beta, run November 16, 2026 over the pilot's scan log from the scheduled runner ([stormglass-ops](../operations.md), exported after the November 16 10:30 scan: 41 scans, October 8 to November 16; dump sha256 `81fb3ef07356afa555eab08f5503c7c49c992a46ec6789848fb885cc0582167c`). The log itself is not committed: every row carries the pilot account profile (QR-5).

### B-KR2 scheduled scans that sent a message, 2026-10-30 to 2026-11-13

| date | slot PT | delivery statuses | scan_late | counts |
|---|---|---|---|---|
| 2026-10-30 | 10:30 | delivered | no | yes |
| 2026-10-30 | 13:25 | no scan | - | no |
| 2026-11-02 | 10:30 | delivered | no | yes |
| 2026-11-02 | 13:25 | delivered | no | yes |
| 2026-11-03 | 10:30 | delivered | no | yes |
| 2026-11-03 | 13:25 | delivered | no | yes |
| 2026-11-04 | 10:30 | delivered | no | yes |
| 2026-11-04 | 13:25 | delivered | no | yes |
| 2026-11-05 | 10:30 | delivered | no | yes |
| 2026-11-05 | 13:25 | delivered | no | yes |
| 2026-11-06 | 10:30 | delivered | no | yes |
| 2026-11-06 | 13:25 | delivered | no | yes |
| 2026-11-09 | 10:30 | delivered | no | yes |
| 2026-11-09 | 13:25 | delivered | no | yes |
| 2026-11-10 | 10:30 | delivered | no | yes |
| 2026-11-10 | 13:25 | delivered | no | yes |
| 2026-11-11 | 10:30 | delivered | no | yes |
| 2026-11-11 | 13:25 | delivered | no | yes |
| 2026-11-12 | 10:30 | delivered | no | yes |
| 2026-11-12 | 13:25 | delivered | no | yes |
| 2026-11-13 | 10:30 | delivered | no | yes |
| 2026-11-13 | 13:25 | delivered | no | yes |

**21 of 22 scheduled scans sent a message** on time; 0 sent one after a `scan_late` event (target 22 of 22; grading band B).

Notes:

- October 30 13:25 has no scan. That day GitHub started every scheduled run after 14:00 PT, past the slot, and the runner then had no catch-up for a missed slot. From November 2 cron-job.org starts both slots through `workflow_dispatch`, and a late run catches up a slot missed earlier that day. The November 2 10:30 scan started 5 minutes late; every slot since has started within 2 seconds of its time.
- No scan in the window logged a `scan_late` event (a start more than 30 minutes after the slot), so none is excluded on that rule.
- 21 of 22 is the B band; the miss cannot be made up inside the window.

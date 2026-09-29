# Operations

## Daily schedule (Pacific time, trading days only)

| Job | Time | Command | Why then |
| --- | --- | --- | --- |
| scan | 10:30 | `scan --slot 10:30` | A-KR1 morning scan; quotes are about 15 minutes old |
| scan | 13:25 | `scan --slot 13:25` | end-of-day scan, 10 minutes after the 13:15 SPX options close |
| mark | 13:45 | `mark` | values every logged proposal at closing quotes (US-09); 1:45 PM matches the user flow diagram |

The diagram's log example shows the second scan at 12:50. That sample is labeled
illustrative, and A-KR2 checks end-of-day proposals against the next morning's
board, which only makes sense for a scan after the close, so the build keeps 13:25.
Change `schedule.slots` and `schedule.eod_slot` together if you want 12:50.

Weekends and NYSE holidays log a `market_closed` scan and send nothing. A scan that
starts more than 30 minutes after its slot says so in the alert and logs a
`scan_late` event. On the early-close days (November 27 and December 24, 2026) SPX
options stop at 10:15 PT, so the 13:25 scan answers NO ADVICE (stale); the mark job
accepts any board updated within 20 minutes of that day's close, so it still runs.

## Setup on one machine (through Alpha)

```powershell
python -m spx_quant profile set --net-liq 150000 --margin portfolio --bp-cap 0.08 --dt-limit 2 `
    --notify email --email-to you@example.com
.\deploy\windows\register_tasks.ps1
```

The PC must be on Pacific time. The script sets WakeToRun so a sleeping laptop wakes
for the slot; a laptop that is shut down still misses it, which is why Beta moves to a
server.

## Beta host (from November 16)

A small Linux VM (proposal 5.5 prices a Hetzner CX23). Install Python 3.11+, clone the
repo, set the clock to Pacific, then edit and load `deploy/cron/crontab.example`.
Deploying an update is `git pull`; cron starts a fresh process each slot.

## Notification channels

Credentials are environment variables, never files in the repo (QR-5).

| Channel | Variables | Notes |
| --- | --- | --- |
| email | `SPX_QUANT_SMTP_HOST`, `SPX_QUANT_SMTP_PORT` (587 STARTTLS, 465 SSL), `SPX_QUANT_SMTP_USER`, `SPX_QUANT_SMTP_PASSWORD`, optional `SPX_QUANT_SMTP_FROM` | Gmail needs an app password (Google Account, Security, App passwords) |
| discord | `SPX_QUANT_DISCORD_WEBHOOK` | channel settings, Integrations, Webhooks, New Webhook, copy URL |

`python -m spx_quant notify-test` sends one message on the profile's channel. The user
flow diagram shows email as the default and Discord as the alternative; confirm with
the mentor by October 9 (US-07).

## Repeat policy: short "no change" messages (decided 2026-09-28)

US-07-AC2 and the diagram (Part 4 screen 9, Part 5 notes) say an unchanged scan sends
no second message. B-KR2 says every scheduled scan sends one. The build follows
B-KR2 with `notify.repeat_policy = "brief"`: when a scan repeats the last delivered
decision, it sends a short NO CHANGE message instead of the full alert. The note still
carries the quotes, both timestamps and, for a proposal, each leg's bid and ask, so
B-KR3 holds. The log stores exactly the text that was sent, plus `repeat_of` pointing
at the earlier alert.

`repeat_policy = "suppress"` restores silence (and fails B-KR2).

Proposal wording to update so the documents agree:
* US-07-AC2: "then no second full alert is sent; a short no-change notice names the
  earlier alert."
* Diagram Part 5 note 2 and the log row "11-03 12:50 same, no alert" say the same
  thing the old way.
* Diagram Part 5 note 1 says skipped scans, no-fit results and unset assumptions send
  nothing. The build sends them as NO ADVICE or STAND DOWN messages, because B-KR2
  counts a "no advice" notice as a message.

## Evidence commands

```bash
python -m spx_quant kr a1                    # Oct 5-16 by default
python -m spx_quant kr a2 --plant            # includes the planted-row proof
python -m spx_quant kr a3 > docs/results/a-kr3.md
python -m spx_quant kr b1                    # Oct 30 - Nov 13 by default
python -m spx_quant kr b2
python -m spx_quant kr b3
```

Each prints a markdown table. Commit the output. The exit code is 0 only when the
target is met.

## Cutting over from the shadow log

The cloud scheduled task "SPX Quant shadow log" still runs `shadow-runner.py` once a
day at 2:30 PM PT and keeps its own JSONL log. It opens one lot every day regardless
of the gate, which is useful for measuring the gate and useless for A-KR1. Keep it
running until the scheduled `scan` jobs have logged a clean week, then pause it.

## Open decisions this build exposed

1. **Delta convention for the delta:theta rule.** Delta is counted in SPX-equivalent
   shares (one XSP lot is a tenth of an SPX lot) so the same structure gets the same
   ratio on either ticker. If the mentor's 1:2 limit assumes a different unit (for
   example beta-weighted SPY deltas), the limit value needs to change with it.
2. **Portfolio-margin calibration.** The engine computes the regulatory floor. Put one
   strangle in the broker's trade ticket, compare buying power, and set
   `margin.pm_house_multiplier` to the ratio.
3. **Worst case against the account.** The worst case now follows the diagram's
   screen 8: an instant 10% index drop with volatility up 10 points. Every proposal
   states it as a percent of net liquidation, but no rule limits it. The 8% cap limits
   buying power, and buying power is not the most you can lose. On the September 28
   close a $150,000 portfolio-margin profile gets five XSP naked puts using $11,204 of
   buying power with a stress worst case of -$20,728 (14% of the account). A
   `max_worst_case_pct` profile field would size contracts down until the worst case
   fits.
4. **How A-KR2 reads "checked against the next 10:30 scan".** The script checks an
   end-of-day proposal's legs for listing, bids, liquidity and quote age on the next
   morning's board. The credit is checked against the quotes it was built on, not the
   next morning's: one night of theta moves a strangle's price by more than its whole
   bid-ask width, so an overnight credit check could never pass. Worth one sentence in
   the proposal's change log.
5. **Loss stop definition.** `management.loss_multiple = 2.0` means cost to close is at
   least twice the credit (a loss of one credit), matching the shadow runner. Some
   traders mean a loss of two credits.

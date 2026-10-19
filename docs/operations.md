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

## Cloud schedule (from October 8, 2026)

Cloud scheduled tasks run the scans so the laptop does not have to be on:

| Task | Time (PT) | Steps |
| --- | --- | --- |
| SPX Quant 10:30 scan | weekdays 10:30 | clone `main`, load the log, `scan --slot 10:30`, send the outbox through Gmail and record each send, save the log |
| SPX Quant end-of-day scan and mark | weekdays 13:25 | same, with `scan --slot 13:25`, then record decisions from email replies, `mark`, save the log, `kr a1` |
| SPX Quant weekly report | Fridays 13:50 | clone `main`, load the log, `report`, email it (read-only; the log is not changed) |

Alerts go out through the task's Gmail connector (channel `gmail`): the scan queues
the message in the log, `outbox` lists what is queued, and `delivered ID --ref MSG`
records the send so B-KR1 can time it. A failed send is recorded with
`delivered ID --failed ERROR`; after three failures the alert leaves the outbox and a
`delivery_failed` event goes into the weekly report. No password or webhook is stored.

Decisions come back as email replies. Reply to an alert with ACCEPTED, DECLINED,
MODIFIED <contracts> or (later) CLOSED as the first word; the end-of-day task finds
the reply and runs `reply ID "<text>" --ref <reply id>`, which never counts the same
reply twice. `decide` does the same from the command line.

Each run starts in an empty container, so the log lives between runs as the project
document `claude/quant-log.sql`: a SQL dump that ends with a sha256 line.
`deploy/cloud/logdoc.py load` refuses a copy whose checksum does not match, so a
damaged copy never replaces the log. The profile ($150,000, portfolio margin) is set
fresh on every run and is never committed (QR-6). The 13:25 run has about 20 minutes
of slack: after the 13:15 close the quotes age past the 30-minute limit around 13:45.

The older "SPX Quant shadow log" task (2:30 PM PT) keeps running beside these; it
writes its own documents and does not count toward A-KR1.

## Setup on one machine (through Alpha)

```powershell
python -m spx_quant profile set --net-liq 150000 --margin portfolio --bp-cap 0.08 `
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
| gmail | none | queued in the log and sent by the cloud task's Gmail connector (`outbox`, `delivered`) |

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
python -m spx_quant kr rc1                   # Oct 5 - Dec 8: proposals that reached their worst case
python -m spx_quant kr rc2 --broker marks.csv  # engine marks vs your tastytrade marks
python -m spx_quant kr rc3                   # decisions on delivered proposals
python -m spx_quant kr s1                    # proposals over remaining buying power
python -m spx_quant report --end 2026-10-16  # the weekly report for any week
```

RC-KR2 needs the broker's numbers, which only you can see: for positions you took,
write the P/L tastytrade shows at the close into a CSV with the columns
`alert_id,market_date,broker_pnl`, one row per position per day you record.

Each prints a markdown table. Commit the output. The exit code is 0 only when the
target is met.

## Cutting over from the shadow log

The cloud scheduled task "SPX Quant shadow log" still runs `shadow-runner.py` once a
day at 2:30 PM PT and keeps its own JSONL log. It opens one lot every day regardless
of the gate, which is useful for measuring the gate and useless for A-KR1. Keep it
running until the scheduled `scan` jobs have logged a clean week, then pause it.

## Account tiers and limits (decided 2026-10-06)

These were waiting on the mentor. I set them myself so the Alpha window runs on real
defaults; every one is still tagged unvalidated and Jonathan can override any of them.

| Tier | Net liq | Margin | Delta:theta default | BP per position | Worst case per position |
|---|---|---|---|---|---|
| starter | under $100,000 | Reg-T only | 1:2 | 8% | 5% |
| standard | $100,000 to $999,999 | Reg-T or portfolio | 1:2 | 8% | 5% |
| large | $1,000,000 and up | Reg-T or portfolio | 1:7 | 8% | 5% |

Pilot profile: $150,000, portfolio margin (standard tier).

- **Delta is SPY-weighted.** Delta in the ratio is counted the way tastytrade
  beta-weights a portfolio: SPY deltas, the dollar P/L of a $1 move in SPY (SPY taken
  as SPX/10, beta 1). One XSP lot of a 0.16-delta put is about 16 SPY deltas; the same
  SPX lot is about 160. Before this the engine counted SPX-equivalent shares, which is
  ten times smaller. Reason: the mentor's numbers only make sense in SPY units. At
  1:2 in SPX shares a 1% index move would cost about 38 days of theta, which nobody
  selling premium for theta would call "theta as the primary income driver". At 1:2 in
  SPY deltas the same move costs about 4 days. tastylive uses the same unit and the
  same number: beta-weighted deltas, and a delta/theta ratio of about 0.5 (1:2) as the
  target for a short-delta book.
- **Delta:theta 1:2 under $1M, 1:7 at $1M and up.** From the August call: 1:2 "is the
  limit, I would not be more directional than that"; with millions 1:2 is "too much",
  so "we'll try to get closer to like 1:10, 1:7". 1:7 is the edge of his normal range
  for large accounts. On a day he wants to lean directional he said 1:4 or 1:5 is fine;
  that is a `--dt-limit 4` override, not the default.
- **Consequence:** a lone 16-delta naked put is about 1:0.7, so it is refused as too
  directional at every tier. Strangles, which the mentor called "our bread and
  butter", pass easily (about 1:59 on the September 28 close). Naked puts come back
  only with a looser `--dt-limit`.
- **Portfolio margin needs $100,000.** tastytrade requires $125,000 to open portfolio
  margin and $100,000 to keep it, so a portfolio profile under $100,000 is rejected
  with a message to use Reg-T. The starter tier exists to say that plainly. At an 8%
  cap, one XSP strangle under Reg-T (about $8,400 to $9,000 of buying power) does not
  fit until about $105,000 to $113,000 of net liq, so a starter account will mostly see
  stand-downs.
- **8% buying power per position (unchanged).** It is the value in US-01-AC1. At 8%,
  three to six positions fill 25% to 50% of net liq, the total buying-power range
  tastylive commonly cites (I have not pinned a page for that range yet).
- **5% worst case per position (was 10%).** The worst case is an instant 10% index
  drop with volatility up 10 points. At 10% per position, six open positions could
  lose 60% in that one event; at 5% the same book loses at most about 30%. On the
  September 28 close the pilot's strangle uses $3,935 of a $7,500 limit, so the change
  does not cut the pilot's size; it binds when buying power is loose (a 20% cap, or the
  elevated-volatility rows in A-KR3).
- **A-KR3 sizes moved** from $25k / $75k / $150k / $1.5M to $100k / $150k / $500k /
  $1.5M, because portfolio margin under $100,000 is no longer a valid profile. The
  matrix now runs on tier defaults instead of a hard-coded 1:2.

## Open decisions this build exposed

1. **Portfolio-margin calibration.** The engine's scan range is now tastytrade's
   published minimum for equity indices (-15% to +10%), not the regulatory floor
   (-8% to +6%). It is still a model. To match the broker exactly:
   `python -m spx_quant margin-check` prints the latest proposal as a ticket; enter it
   in tastytrade without sending, then run
   `python -m spx_quant margin-check --broker-bp <ticket BP> --apply`. That writes
   `margin.pm_house_multiplier` = broker / engine and records the check in its
   provenance. Repeat on a strangle once one is proposed.
2. **How A-KR2 reads "checked against the next 10:30 scan".** The script checks an
   end-of-day proposal's legs for listing, bids, liquidity and quote age on the next
   morning's board. The credit is checked against the quotes it was built on, not the
   next morning's: one night of theta moves a strangle's price by more than its whole
   bid-ask width, so an overnight credit check could never pass. Worth one sentence in
   the proposal's change log.
3. **Loss stop definition.** `management.loss_multiple = 2.0` means cost to close is at
   least twice the credit (a loss of one credit), matching the shadow runner. Some
   traders mean a loss of two credits.

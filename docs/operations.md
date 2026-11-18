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

## Schedule (Beta, from October 30, 2026)

The scans run on GitHub Actions in a private repository, `stormglass-ops`, because the log
carries the pilot's account size (QR-5). Each run checks out this repository's `main`, loads
the encrypted logs, does its job and commits the logs back.

| Run | Time (PT, weekdays) | Steps |
| --- | --- | --- |
| 10:30 slot | 10:30 | `scan --slot 10:30`; the alert is emailed (Gmail SMTP) and the send recorded |
| 13:25 slot | 13:25 | `scan --slot 13:25` and its email, then decisions from email replies, then `mark` at the closing quotes |
| weekly report | Fridays after the close | `report`, emailed |
| Monday outlook | Mondays, about 05:30 | `digest monday --book paper --send`; skipped once Temporal sends it (below) |

GitHub starts scheduled runs late, by hours on some days, so an outside cron starts the two
slot runs on time through `workflow_dispatch`. The GitHub crons stay as late backups: a run
that starts early waits for its slot, and a slot already logged is skipped.

A failed send is recorded with its error and retried up to three times; after that a
`delivery_failed` event goes into the weekly report. The email password is a repository
secret (a Gmail app password), never a file.

The Monday outlook is one email of the open positions: four totals, the 10 positions closest
to expiry and the 10 with the largest stated worst case (the stress-test loss printed in each
proposal), with buying power next to it. It reads one of two books. A book is a set of
positions followed from entry to exit: `--book taken` holds the proposals you accepted or
modified, at the lots you took, until you reply CLOSED or they expire; `--book paper` holds
every proposal at full size until the first daily mark that flags the profit target or
settles. The pilot gets the paper book for now. `--send` writes a `digest_monday` event with
the date, so a second run that day sends nothing; a send that fails three times is a
`delivery_failed` event in the weekly report. The GitHub cron that starts it can be hours
late, so a Temporal Schedule takes it over once the Temporal account is connected (see
"Temporal: the digest emails on a schedule" below).

```bash
python -m spx_quant digest monday --book paper                 # print today's outlook
python -m spx_quant digest monday --date 2026-11-16 --html outlook.html --out outlook.txt
```

Decisions come back as email replies. Reply to an alert with ACCEPTED, DECLINED,
MODIFIED <contracts> or (later) CLOSED as the first word; the 13:25 run reads replies over
IMAP and runs `reply ID "<text>" --ref <message id>`, which never counts the same reply
twice. `decide` does the same from the command line.

The log moves between runs as a SQL dump that ends with a sha256 line
(`deploy/cloud/logdoc.py`), encrypted with AES-256. `load` refuses a copy whose checksum
does not match, so a damaged copy never replaces the log. The profile is set fresh on every
run from repository secrets and is never committed (QR-5). The 13:25 run has about 20
minutes of slack: after the 13:15 close the quotes age past the 30-minute limit around 13:45.

The older "StormGlass shadow log" task (2:30 PM PT) keeps running beside these; it writes
its own documents and does not count toward any key result.

## Two users at once

Proposal 4.5 runs both pilot users off one copy of the code: each user has their own
profile, their own log and their own schedule entry. Nothing else is shared except
`config/params.toml`, which a scan only reads.

```
same code, same slot
├─ pilot   profile A ─▶ scan ─▶ log A ─▶ alert to A
└─ demo    profile B ─▶ scan ─▶ log B
```

`tests/test_two_users.py` starts two `scan` processes at the same moment on the recorded
September 28 board, one per user ($150,000 portfolio margin and $250,000 Reg-T), and checks:

- each log holds exactly its own scan and alert, and the alert carries its own profile
- the same board is sized per account: 1 XSP strangle for one user, 2 for the other
- each user's outbox addresses only that user
- alert IDs are counted per log: both logs get the same first ID, and a second scan
  adds `-2` only in the log it ran in

From October 30 a second, simulated user runs live beside the pilot in every slot run:
$250,000, Reg-T, no email, with its own encrypted log. Both scans start at the same
moment. I operate it as a demonstration profile. It is not a pilot user and records no
decisions.

Each run prints the two logs side by side; to do it by hand, load both dumps with
`logdoc.py load`, then:

```bash
python deploy/cloud/side_by_side.py pilot.db demo.db --labels pilot demo
```

One row per scheduled scan: when each user's scan started, what it answered, and the
gap between the two start times. Account sizes stay out of the table (QR-5).

## Linux host (optional)

The GitHub runner replaces the rented host in proposal 4.5: it runs unattended and costs
nothing. If a host is wanted later: a small Linux VM (proposal 5.5 prices a Hetzner CX23).
Install Python 3.11+, clone the repo, set the clock to Pacific, then edit and load
`deploy/cron/crontab.example`. Deploying an update is `git pull`; cron starts a fresh
process each slot.

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

## Email layout (changed 2026-11-12)

Every alert email carries two bodies. The plain text is the logged record (`alert.text`, QR-6)
and the fallback for clients that show no HTML. The HTML (`alert.html`, built by `htmlmail.py`)
shows the same facts as a card: headline, four key numbers (credit, chance of profit, worst
case, buying power), the order table, then sizing, risk and market detail. Styles are inline
because mail clients drop `<style>` blocks. If the HTML fails to build, the scan still logs and
sends the plain text, and an `html_failed` event records why.

A proposal email says nothing about the other positions you hold. When held positions cut the
size, the email says only "Sized down from 3 to 2 lots to fit your remaining buying power."
The list of held positions and the dollars left (US-13-AC1) stays in the log: `scan.detail.notes`.

## Settings site (added 2026-11-15)

Account settings live on a web page instead of a file. `cloud/` holds it:

- `cloud/template.yaml` (AWS SAM, a CloudFormation dialect for serverless apps): a Cognito user pool, one
  Lambda serving the page and the profile API through an HTTP API, and a DynamoDB table `stormglass-users`
  with one row per email.
- Sign-in is an emailed 6-digit code (Cognito custom auth, `cloud/app/auth.py`). No passwords. Only invited
  emails exist in the pool, and an unknown email fails the same way a wrong code does. Three wrong codes end
  the attempt; a code works for 10 minutes.
- The API (`cloud/app/api.py`) takes the email from the signed-in token, never from the request, and checks
  every save with `spx_quant.profile.validate`, so the page and `profile set` accept the same values.
- The scans read this table once the runner repo has the variable `AWS_RUNNER_ROLE_ARN` (the stack's
  `RunnerRoleArn` output). Before each run, `deploy/cloud/siteprofile.py EMAIL OUT.json` fetches the pilot's
  row with the AWS command line tool, checks it with `profile.validate` and writes the run's profile file.
  With the alerts switch off the profile's channel is `none`. No variable, no saved row, a value that fails
  the check or any AWS error: the script exits 1, writes nothing, and the runner uses its secrets as before.
- After a run saves its encrypted logs, it copies the plain dumps (`logdoc.py dump` format) to the bucket
  `stormglass-logs-<account id>` as `logs/<email>.sql` and `logs/auto.sql`, where the Temporal worker
  (item 8) will read them. The bucket blocks all public access and encrypts at rest (SSE-S3, keys managed
  by S3). A failed copy prints a line and changes nothing else; the encrypted log stays the record.
- The runner signs in with its own role (`RunnerRole` in the template), not the deploy role. It can do two
  things: `dynamodb:GetItem` on the users table and `s3:PutObject` under `logs/`. Only runs on the main
  branch of the runner repo can take it.

Deploys run from GitHub Actions in the runner repo (`site.yml`, action `deploy`), which signs in to AWS with
OIDC (a short-lived token GitHub issues per run) and the `stormglass-deploy` role. `cloud/bootstrap.yaml`
creates that role once; it can only touch StormGlass resources. The same workflow's `invite` action adds a
user. Tests: `pip install -r cloud/requirements-dev.txt`, then `python -m unittest tests.test_cloud`
(the API tests skip when moto is missing).

## Temporal: the digest emails on a schedule (added 2026-11-17)

Temporal is a service that runs a function, called a workflow, and records each step, so a crash or a
timeout resumes from the last finished step instead of starting over. Steps that touch the outside world
are activities, and Temporal retries them. It replaces the GitHub cron for the Monday outlook, which
GitHub can start hours late. Built and tested; not connected to a Temporal account yet.

- `cloud/worker/workflows.py`: `DigestWorkflow(kind, date)`. A Temporal Schedule (a timer Temporal keeps,
  in a named time zone) starts it with the kind only. That run works out the market date and starts a child
  run with the id `digest-<kind>-<date>`. Temporal refuses a second run under an id that already finished,
  so a date sends once, whether the schedule or a person started it. A date that failed can be started again.
- `cloud/worker/activities.py`: `list_users` reads the settings table and keeps the users whose Monday (or
  Friday) switch is on, with the book each chose on the site. `send_digest` downloads the user's plain log
  copy from the bucket (`logs/<email>.sql`), loads it into a temporary SQLite file with `logdoc.py`, builds
  the email with `spx_quant.digest` (the same code as the command line) and sends it over the Gmail account
  the alerts use. Each send gets three tries, 30 and 60 seconds apart. No log copy yet means nothing is
  sent for that user. One user's failure does not hold back the others; the run is marked failed at the end.
- `cloud/worker/worker.py`: the worker, the process that runs workflow and activity code. It is a Lambda
  function (`stormglass-worker`) that Temporal Cloud invokes when a task is waiting, so nothing runs between
  emails. This is Temporal's Serverless Workers feature, in public preview, through `run_worker` in the
  Temporal Python SDK. The API key is read from SSM Parameter Store, not from the function's environment.
  The function can scan the users table, read `logs/` in the bucket and read the two mail parameters and
  the key. It cannot write anywhere.
- `cloud/schedules.py`: creates or updates the schedules, Mondays 06:00 and Fridays 17:00
  America/Los_Angeles, one per digest the engine builds (`digest.KINDS`). `--show` prints the plan.
- Temporal's records hold the workflow inputs, so user email addresses are stored in Temporal Cloud. No
  account numbers, settings or log rows leave AWS.

Going live, in order (the full guide with cost and teardown is item 10 of issue #63):

1. In Temporal Cloud: create a namespace in an AWS region and an API key.
2. In the runner repo: variables `TEMPORAL_ADDRESS` (host:port) and `TEMPORAL_NAMESPACE`, secret
   `TEMPORAL_API_KEY`. Run `site.yml` with `deploy`. With all three set it stores the key in SSM, builds the
   worker with `sam build` and adds the function to the stack; the output `WorkerFunctionArn` is new.
3. In Temporal Cloud: let Temporal invoke the function (its "Launch Stack" button creates an IAM role from
   Temporal's own template; give it `WorkerFunctionArn`), then create a Worker Deployment Version with
   deployment name `stormglass` and build id `1` pointing at the function and set it current.
4. Run `site.yml` with `schedules`.

From step 2 on, `run.sh` sees `TEMPORAL_ADDRESS` and skips its own Monday outlook, so nobody gets two; do
steps 2 to 4 in one sitting. Without the variables, deploys and scans behave as before.

Tests: `python -m unittest tests.test_temporal` (skipped without the packages in
`cloud/requirements-dev.txt`). The workflow runs on the SDK's time-skipping test server, the activities
against moto's stand-in for AWS. The CI job `cloud` runs these, `test_cloud` and `cfn-lint` on every push.

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

The cloud scheduled task "StormGlass shadow log" still runs `shadow-runner.py` once a
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

1. **Portfolio margin is a model.** The engine scans tastytrade's published range for
   equity indices (-15% to +10%), not the regulatory floor (-8% to +6%). The broker's
   number can differ.
2. **How A-KR2 reads "checked against the next 10:30 scan".** The script checks an
   end-of-day proposal's legs for listing, bids, liquidity and quote age on the next
   morning's board. The credit is checked against the quotes it was built on, not the
   next morning's: one night of theta moves a strangle's price by more than its whole
   bid-ask width, so an overnight credit check could never pass. Worth one sentence in
   the proposal's change log.
3. **Exit rules.** Since the 2026-10-19 rules pivot the 50% profit target is the only exit
   (`management.profit_target`; see docs/results/rules-pivot.md). The loss stop, 21-DTE
   exit and tested-strike exit were removed from the code on October 21.

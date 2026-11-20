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

Going live is stage 3 of the deploy guide below. Once the runner repo has the variable `TEMPORAL_ADDRESS`,
`run.sh` skips its own Monday outlook, so nobody gets two. Without the Temporal variables, deploys and
scans behave as before.

Tests: `python -m unittest tests.test_temporal` (skipped without the packages in
`cloud/requirements-dev.txt`). The workflows run on the SDK's time-skipping test server, the activities
against moto's stand-in for AWS. The CI job `cloud` runs these, `test_cloud` and `cfn-lint` on every push.

## Temporal: one workflow per proposal (added 2026-11-18)

`ProposalWorkflow` in `cloud/worker/workflows.py` follows one proposal from the scan that logged it until
the position is over. Its id is `proposal-<user>-<alert id>`, where the user is the email the alerts go to,
or `auto` for the autonomous account. The log stays the record; the workflow adds two things: one email when
a position you took reaches the profit target, and a place to look up where any proposal stands.

- It learns what happened through signals. A signal is a message a client sends to a running workflow.
  `decision` carries a reply the runner recorded (accepted, modified with the lots taken, declined, closed).
  `marked` carries a daily mark (date, P/L, whether the profit target is flagged, whether it settled).
- It waits for a decision until expiration at most. A declined proposal ends its run. A proposal nobody
  answered ends as `not_taken` at the settlement mark, or 4 days after expiration if that mark never comes.
- Once taken, it follows the marks. The first time a mark flags the profit target it runs the activity
  `send_target`, which builds the email with `spx_quant.digest.target` from the log copy in the bucket and
  sends it over the Gmail account the alerts use. One email per position. Replying CLOSED to it records the
  close, the same as replying to the proposal. A mark more than a day old sends nothing, so connecting
  Temporal to a log with long-open positions does not mail old news. A send that fails (5 tries over 15
  minutes) is tried again at the next flagged mark and never ends the run. The site's alerts switch turns
  the email off. The autonomous account has no inbox and gets none.
- It ends on CLOSED or on the settlement mark and returns the P/L of the lots held at the last mark.
- `status` is a query, a read of the run's state that changes nothing: status (`proposed`, `taken`,
  `declined`, `not_taken`, `closed`, `settled`, `unsettled`), lots, P/L, the date of the last mark and what
  happened to the email. In the Temporal Cloud page for the run, or
  `temporal workflow query --workflow-id proposal-<user>-<alert id> --type status`.

The runner feeds it. `deploy/cloud/lifecycle.py DB USER` runs at the end of every scan and mark run, after
the log copy is in the bucket, and only when the runner repo has the variable `TEMPORAL_ADDRESS`. For each
proposal still in play (not settled, or settled, declined or closed within the last 3 days; a NO CHANGE
repeat only if it got a reply) it starts the run if there is none and sends the decisions and marks the run
has not seen. Each signal carries the id of its log row. The workflow skips an id it already handled and
publishes the last ids as its memo (a note on the run that can be read without a worker), which is how the
next sync knows where to resume. A run with no memo yet has not been picked up by a worker, so the sync
leaves it alone (`waiting` in its output) instead of queuing the same rows again. Nothing is written to the
log, a sync cut short is finished by the next one, and an error prints a line and leaves the scan, the mark
and the saved logs as they were. `--show` prints the plan and connects to nothing.

What leaves AWS for Temporal Cloud with this: the user's email (in the workflow id), alert ids, expiration
dates, lots, each decision and each mark's P/L. No account size, settings, strikes or quotes.

Going live needs nothing beyond stage 3 of the deploy guide below: the scan workflow (`run.yml`) reads the same two
variables and the secret `TEMPORAL_API_KEY`, and installs the Temporal SDK for this one step. If a worker
without `ProposalWorkflow` was deployed before, deploy again with a new build id (variable
`WORKER_BUILD_ID`) and register that version in Temporal Cloud ("Updates" in the guide). The first sync starts a run for every
proposal in play and sends its whole history, a few hundred signals once.

## Deploy guide: AWS and Temporal (added 2026-11-19)

How to put the settings site and the Temporal workflows live, what they cost, and how to remove them.
Nothing here is deployed yet. The steps were checked on November 19, 2026 against the AWS and Temporal
documentation, the SAM command line tool's source (1.173.0) and the Temporal command line tool (1.10.1).
They have not been run against a real account, so expect to adjust a label or two. Temporal's Lambda
workers (Serverless Workers) are in public preview and Temporal says the setup may change.

There are three stages. Each one leaves the scans working if you stop after it, and the scans keep
running on the runner's secrets until the stage 2 variable exists.

| Stage | Result | Where the work happens |
| --- | --- | --- |
| 1 | the settings site is up and you can sign in | AWS console once, then the `site.yml` workflow |
| 2 | the scans use the settings saved on the site and copy their logs to the bucket | one variable in the runner repo |
| 3 | Temporal sends the Monday outlook and follows each proposal | Temporal Cloud, AWS console, runner repo |

Everything lives in one AWS region, `us-west-2` (Oregon); `site.yml` and `run.yml` in the runner repo
(`stormglass-ops`) name it. "Variable" and "secret" below mean the runner repo's Settings, Secrets and
variables, Actions. A stack is a set of AWS resources that CloudFormation creates, updates and deletes
together from one template file.

### Stage 1: the settings site

1. Sign in to the AWS console and switch the region to US West (Oregon).
2. CloudFormation, Create stack, upload `cloud/bootstrap.yaml`, name it `stormglass-bootstrap`, keep the
   default parameter, tick the box that acknowledges it creates IAM resources with custom names, and
   create it. It makes two things: the trust that lets GitHub Actions prove which repository a run
   belongs to (an OIDC provider), and the role `stormglass-deploy`, which only the main branch of the
   runner repo can take. If the stack already exists from an earlier try, update it with the current
   file instead, because the role gained a bucket permission on November 16.
3. Copy the stack's `RoleArn` output into the variable `AWS_ROLE_ARN`.
4. In the runner repo, Actions, "StormGlass settings site", Run workflow, action `deploy`. It stores the
   Gmail address and app password the alerts already use in Parameter Store (encrypted, under
   `/stormglass/smtp/`), creates the stack `stormglass-site` and prints its outputs. `SiteUrl` is the page.
5. Run the workflow again with action `invite` and your email. Use the address in the secret
   `STORMGLASS_EMAIL_TO`, because the scans look the settings up by that address.
6. Open `SiteUrl`, enter the email, type the 6-digit code it sends, check the values and press Save settings.

If the deploy fails on a service the account may not use: a new AWS account is on the Free plan, which
AWS limits to "select services". The services used here are Lambda, API Gateway, Cognito, DynamoDB, S3,
Parameter Store, IAM and CloudFormation. I could not find AWS's list of excluded services, so the first
deploy is the test. The error names the resource that failed.

### Stage 2: the scans read the site

1. Copy the `RunnerRoleArn` output of `stormglass-site` into the variable `AWS_RUNNER_ROLE_ARN`.
2. The next scan prints `settings site: using the profile saved ...` and, after the logs are saved,
   `log copied to S3` once per user. If it prints `using the runner's secrets` instead, the line before
   it says why (no saved row for that email, a value that fails the check, or no AWS access).

To go back, delete the variable. The secrets `STORMGLASS_NET_LIQ` and `STORMGLASS_MARGIN` are the
fallback the whole time, so keep them in step with what you save on the site.

### Stage 3: Temporal

Do steps 3 to 7 in one sitting. From step 3 on the runner stops sending its own Monday outlook, and
the Temporal one starts at step 7.

1. Temporal Cloud: create the account (it asks for a credit card). Namespaces, Create Namespace: any
   lowercase name, cloud provider AWS, region `us-west-2`, retention 30 days, authentication method API
   keys. A namespace is one isolated set of workflows. The provider must be AWS for a Lambda worker, and
   a namespace keeps the authentication method it was created with. Retention is how long a finished run stays
   readable, and the once-per-date rule for the digests depends on the finished run still being there.
2. Create an API key: your profile page, API Keys, Create API key. The longest life is 2 years. The key
   is shown once. Temporal emails a warning 30, 20 and 10 days before it expires.
3. Runner repo: variable `TEMPORAL_ADDRESS` = `<namespace>.<account id>.tmprl.cloud:7233`, variable
   `TEMPORAL_NAMESPACE` = `<namespace>.<account id>` (the Namespaces list shows that id, and the Connect
   button on the namespace's page shows the address), secret `TEMPORAL_API_KEY` = the key.
4. Run "StormGlass settings site" with `deploy`. With all three set it stores the key in Parameter Store
   (`/stormglass/temporal/api_key`), builds the worker and adds the function `stormglass-worker` to the
   stack. Copy the new output `WorkerFunctionArn`.
5. Temporal Cloud, your namespace, Workers, Create Worker Deployment. The Launch Stack button on that
   page opens CloudFormation with Temporal's own template, which creates the role Temporal takes to
   invoke the function. Its parameters: `LambdaFunctionARNs` = `WorkerFunctionArn`, `AssumeRoleExternalId`
   = a string you make up (5 to 45 letters and digits; Temporal must present it to take the role, so
   another Temporal customer cannot point their account at your function), `RoleName` as offered. Create
   the stack and copy its `RoleARN` output.
6. Back on the Create Worker Deployment page: name `stormglass`, build id `1` (both must match what the
   function reports: `DEPLOYMENT` in `cloud/worker/worker.py` and the variable `WORKER_BUILD_ID`,
   default 1), compute AWS Lambda, the function's ARN, the role's ARN, the same external id. Save. The
   documentation says a version created on this page becomes the current one. Then Workers, Deployments,
   `stormglass`, Actions on the version, Validate Connection. The same from the command line, with the
   three `TEMPORAL_` values in the environment:

   ```bash
   temporal worker deployment create-version --deployment-name stormglass --build-id 1 \
     --aws-lambda-function-arn WORKER_FUNCTION_ARN --aws-lambda-assume-role-arn ROLE_ARN \
     --aws-lambda-assume-role-external-id EXTERNAL_ID
   temporal worker deployment set-current-version --deployment-name stormglass --build-id 1
   ```
7. Run "StormGlass settings site" with `schedules`. It prints `stormglass-digest-monday: created`.

Checks:

- The next scan ends with one lifecycle line per user, for example
  `lifecycle: 3 started, 41 signals, 0 waiting, 0 finished, 0 failed`. The first
  sync sends each open proposal's whole history. `waiting` counts runs that no worker has picked
  up yet; if it stays above zero for two scans, the worker is not being invoked.
- `temporal schedule trigger --schedule-id stormglass-digest-monday` (same three values in the
  environment) starts the Monday outlook now. It
  sends a real email to every user with the Monday switch on, and that date will not send again.
- Worker output is in CloudWatch, log group `/aws/lambda/stormglass-worker`.

What Temporal's troubleshooting page says about the usual failures: "Invalid connection" on Validate
Connection means a wrong function or role ARN or an external id that does not match. "Task Queue not
registered" means the function started and stopped before it could ask for work, so read its log (a
missing parameter or an expired key). A deployment name or build id that differs from what the function
reports makes Temporal invoke it over and over.

Two gaps on main today. The Friday schedule is created only once `digest friday` is on main (PR #81);
run `schedules` again then. And the runner change that sends the Friday close itself (stormglass-ops
PR #1) needs the same `TEMPORAL_ADDRESS` guard as the Monday step before it merges, or Friday sends twice.

### Updates

- Site or worker code changed on main: run `deploy` again. The stack name is the same, so it updates in
  place and users, saved settings and logs stay.
- Workflow code changed in a way that alters the order of steps: set `WORKER_BUILD_ID` to the next
  number, deploy, create a version with that build id (step 6) and make it current. Then delete the old
  version (`temporal worker deployment delete-version --deployment-name stormglass --build-id 1`). Both
  versions point at the same function, which now reports the new id, and a version whose id the function
  does not report is the invoke-over-and-over case above. Temporal recommends one published Lambda
  version per build id for production; this stack uses the plain function ARN, which its documentation
  allows for development.
- New Temporal API key: put it in the secret and run `deploy`. The function reads the key when a fresh
  copy starts and keeps it while that copy stays warm, so leave the old key enabled for a day before
  deleting it. An expired key stops the digests and the lifecycle sync. It does not touch the scans.
- New Gmail app password: change the two SMTP secrets and run `deploy`.

### Cost

Read on November 19, 2026. Prices change, so check the Billing page in each console after the first week.

AWS. The account is on the Free plan: $100 of credits at sign-up, no charges at all unless you upgrade
to the Paid plan, and the account closes by itself 6 months after it was opened (opened November 15,
2026, so about May 15, 2027) or when the credits run out, whichever is first. AWS then keeps the data
for 90 days, and upgrading within that time keeps the account. Usage here is far inside the allowances
that are free on both plans:

| Service | What this uses in a month | Allowance or price |
| --- | --- | --- |
| Lambda | a few hundred short runs of the site functions; the worker runs for at most 5 minutes at 512 MB when Temporal has work, a few times around each scan. A high guess is 70,000 GB-seconds (memory times run time) | 1 million requests and 400,000 GB-seconds a month free, then $0.20 per million requests |
| Cognito | 1 or 2 users who sign in | 10,000 monthly users free on the Essentials tier, the default for a new pool, with no end date |
| Parameter Store | 3 standard parameters | no charge |
| DynamoDB, API Gateway, S3, CloudWatch logs | a table of a few rows with point-in-time recovery, a few hundred page and API calls, two log copies of a few megabytes written about 90 times each, a few megabytes of function output | prices not looked up; at this size I expect cents a month on the Paid plan |

Temporal Cloud. No monthly fee on the pay-as-you-go plan. It bills actions at $50 per million (the first
5 million), plus 10% of usage for support, plus storage ($0.042 per GB-hour for running workflows,
$0.00105 for finished ones). An action is a billable step: starting a workflow, each activity try, each
signal, each timer, each query. A new account gets $150 of credits that expire after 90 days, and the
card is not charged in that time while credits remain. My estimate for this project, not a measurement:
each mark or reply costs 2 actions (the signal and the timer the workflow sets while it waits for the
next one), so 30 open proposals marked on 21 trading days come to about 1,300 actions, the first sync
adds about 1,000 once, and the two digests add about 40. That is under 5,000 actions a month, about 25
cents. The storage is a few megabytes.

Gmail and GitHub Actions cost nothing more than they do today.

### Turning it off

Temporal only, keeping the site:

1. Delete the variables `TEMPORAL_ADDRESS` and `TEMPORAL_NAMESPACE` and the secret `TEMPORAL_API_KEY`.
   The runner sends its own Monday outlook again and stops the lifecycle sync.
2. Temporal Cloud: Namespaces, the namespace, Edit, Delete Namespace, type `DELETE`. This removes its
   running workflows, schedules and task queues at once and cannot be undone. Do it in the same sitting
   as step 1, or Monday sends twice. Then delete the API key (profile page, API Keys).
3. CloudFormation: delete the stack that Launch Stack created (the Temporal role).
4. The function `stormglass-worker` stays in `stormglass-site`. A deploy without the Temporal variables
   does not remove it, because `sam deploy` reuses a stack's earlier parameter values when none are
   passed. With the namespace and the role gone nothing can invoke it, and Lambda bills only for runs.
   Delete `/stormglass/temporal/api_key` in Parameter Store by hand.

I did not find how to close a Temporal Cloud account. With no namespace there is no usage to bill; ask
Temporal support if the account itself should go.

Everything on AWS:

1. Check that the secrets `STORMGLASS_NET_LIQ` and `STORMGLASS_MARGIN` hold the settings you want, then
   delete the variable `AWS_RUNNER_ROLE_ARN`. The scans are back on the secrets.
2. Do the Temporal steps above if stage 3 was live.
3. S3: empty the bucket `stormglass-logs-<account id>`. CloudFormation cannot delete a bucket with
   objects in it. The encrypted logs in the runner repo are the record; these are copies.
4. CloudFormation: delete `stormglass-site`. This removes the page, the user pool with its invited
   users, the table with the saved settings, the functions, the bucket and the runner role.
5. Parameter Store: delete `/stormglass/smtp/user` and `/stormglass/smtp/password`. The workflow wrote
   them, so the stack does not own them, and one of them is the Gmail app password.
6. CloudWatch, Log groups: delete the groups that start with `/aws/lambda/stormglass-`. Lambda created
   them, they are not part of the stack, and they never expire by themselves.
7. S3 and CloudFormation: `sam deploy` made a stack `aws-sam-cli-managed-default` with a bucket for
   uploaded code. Empty that bucket (the console's Empty button also removes old versions), then delete
   the stack.
8. CloudFormation: delete `stormglass-bootstrap` last, then the variable `AWS_ROLE_ARN`. After this
   GitHub Actions has no way into the account.

On the Free plan, doing nothing also ends it: the account closes at 6 months and AWS erases it 90 days
later.

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

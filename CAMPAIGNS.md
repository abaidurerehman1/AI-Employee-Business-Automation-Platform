# Phase 10 — Marketing campaign automation

Open **Marketing campaigns** in the application. Administrators and managers can
create drafts, record evidenced channel-specific marketing consent, preview CRM
audiences, save segments, generate editable content, and manage campaign controls.
Only administrators can approve or reject campaigns and reconcile uncertain sends.
Employees have read-only campaign and analytics access within their organization.

## Local setup

```powershell
docker compose up -d --build backend worker temporal-worker frontend
docker compose exec -T backend alembic current
```

Phase 10 introduced migration `20261028_0013`; the foundation audit adds
`20261028_0014`. The frontend runs on port 5173 and the API
on port 8000. Temporal uses the existing namespace and task queue. Campaigns do
not introduce a second mail or SMS provider or a second sending queue.

## Required provider setup

Use the existing variables in `backend/.env`, never commit real credentials:

| Capability | Configuration |
| --- | --- |
| AI drafts | `OPENAI_API_KEY`, existing OpenAI model and input/output budgets |
| Gmail | Existing OAuth client configuration and workspace Gmail authorization |
| Resend | Valid `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, verified sender-domain DNS |
| Email marketing | Public HTTPS `MESSAGING_PUBLIC_BASE_URL`, stable `MESSAGING_UNSUBSCRIBE_SECRET` |
| Resend events / receiving | `RESEND_WEBHOOK_SECRET`, signed events to `/api/v1/messaging/webhooks/resend`; supported receiving address and valid API key for inbound replies |
| SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`; required Twilio sender registration and account permissions |
| SMS events and replies | Public callback `/api/v1/messaging/webhooks/twilio/{organization_id}`, configured on the Twilio number for inbound messages |
| Durable execution | Existing `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE` and running Temporal worker |

Marketing campaigns normally require a public HTTPS unsubscribe endpoint.
For a local self-test only, set `CAMPAIGN_ALLOW_LOCAL_GMAIL_SELF_TEST=true` in
`backend/.env`, keep `APP_ENV=development`, and use
`MESSAGING_PUBLIC_BASE_URL=http://localhost:8000`. Every eligible recipient must
be the connected Gmail address itself; an audience containing any other recipient
is blocked. The local signed unsubscribe link remains in the email. Consent,
suppression, approval and duplicate prevention still apply. The exception is
rechecked immediately before dispatch and is unavailable in production, even if
the flag remains enabled. It cannot be used with Resend.

Once a public HTTPS API endpoint is available, set its address in
`MESSAGING_PUBLIC_BASE_URL`, set `CAMPAIGN_ALLOW_LOCAL_GMAIL_SELF_TEST=false`, and
restart backend/workers. Return pending/approved campaigns to Draft and obtain
fresh approval after changing the sender/URL configuration. A real public API
deployment or appropriately configured development tunnel is needed for sending
marketing campaigns to other people.

The new optional limits are `CAMPAIGN_MAX_RECIPIENTS` (1000),
`CAMPAIGN_EMAIL_INTERVAL_SECONDS` (2), `CAMPAIGN_SMS_INTERVAL_SECONDS` (1), and
`CAMPAIGN_ALLOWED_SMS_PREFIXES` (JSON list, empty means no additional country
restriction). The existing `MESSAGING_HOURLY_LIMIT` also applies. Set these to
match the actual provider account, sender registration, and recipient regions.
Country calling-prefix filtering is an additional configured restriction; it
does not determine a recipient's residence or replace country-specific policy.

## Frontend test flow

1. Add a synthetic CRM contact with an email or E.164 phone number you control.
2. In **Marketing consent**, record the channel and real evidence. Imported
   contacts have no marketing permission by default. Suppressed contacts remain
   excluded even if a later consent record says granted.
3. Create a campaign, choose the channel, provider, and optional AI employee.
4. Preview the audience using contact name, company, linked lead stage/owner,
   or previously recorded provider engagement. Save a reusable segment if useful.
5. Write a message, load a Phase 9 template, or generate an editable AI draft.
6. Review personalized content and choose a scheduled instant and sending window.
   The date/time input is explicitly in the browser's local time. Sending windows
   use the separate IANA timezone. Overnight windows can be represented with
   separate campaigns; a single window must have an end hour after its start.
7. Save the draft, request approval, review the audience and content as an
   administrator, and approve. Starting is a separate explicit human action.
8. Start or schedule. Check progress, recipient state, attempts, provider events,
   CSV export, pause/resume, cancellation, and opted-out exclusions.

Supported personalization variables are `first_name`, `name`, `email`, `phone`,
and `company_name`. Missing values block approval. `job_title`, location, industry
and tags are not in the existing CRM schema and are not invented or exposed as
filters. CRM audience filtering is bounded by `CAMPAIGN_MAX_RECIPIENTS`; narrow
large audiences before approval. Contact/company selectors show up to 100 matching
records; contact-name search can narrow the consent selector.

## Approval and execution guarantees

- Content, rendered recipients, schedule, sender identity and revision are saved
  in an approval snapshot with a digest, approver and timestamp. Recipient rows
  store the rendered approved messages. Existing Phase 9 message templates and
  outbound message/event tables are reused. Schedule and audience configuration
  are stored on the campaign; analytics are calculated from actual records.
- Material edits return a campaign to Draft, increment its revision and invalidate
  approval. Prior approval snapshots and audits remain. Running campaigns are
  immutable; duplicate them for new content/audiences instead.
- A stable workflow ID is used for each campaign revision. Activities contain
  database and network work; workflow code only coordinates durable timers and
  activity calls. Continue-As-New bounds workflow history. Database state is
  rechecked after each wait; pause/resume/cancel do not depend on receiving a signal.
- Pause shares the campaign row lock with dispatch claims. Once pause commits,
  no new message can be claimed. A message already marked Sending is in flight
  and can finish. Unclaimed cancelled recipients are never dispatched.
- Consent, current contact address, suppressions, sender identity, sending windows
  and configured limits are rechecked before dispatch. A changed sender blocks
  the campaign and requires a fresh draft/approval.
- Transactional/individual Phase 9 messages remain separate from marketing
  campaigns. AI generation cannot approve, enroll contacts or launch campaigns.
- Phase 9 queue recovery excludes campaign messages. Temporal owns their progress.
  A recipient has one unique message/idempotency key per approved revision.
- Explicit HTTP 429 rejection uses durable backoff with at most three attempts.
  Other known 4xx rejection is permanent. Timeouts, ambiguous responses and 5xx
  are Unknown, never blindly retried. Worker interruption during a send also
  becomes Unknown; the campaign pauses for review.
- Reconciliation requires an administrator and recorded provider evidence. Marking
  accepted requires a provider message ID. Confirming Not Sent for a retry requires
  a paused campaign, no accepted provider ID, and remaining retry budget. Resume
  continues the same message. Treat this as a manual operational decision based
  on provider records, not an automatic assertion of delivery failure.
- Existing signed webhook handlers deduplicate events and preserve terminal
  status ordering. Suppressions/STOP/unsubscribe revoke channel consent and are
  audited. Associated campaign events add activity to linked CRM leads.

## Provider reporting limits

Accepted means the provider accepted the request; it does not prove inbox delivery.
Gmail's send-only connection does not provide delivery/open/click/reply tracking.
Replies to Gmail stay in Gmail. Resend tracking depends on provider/domain settings;
reported zero means no recorded event and is not proof of zero engagement.
Opens/clicks may be affected by recipient privacy software. Unsupported engagement
metrics are returned as null and displayed as Unavailable. Date filters apply to
provider-event metrics and timeline; recipient totals/statuses describe the full
approved revision. Timeline/attempt audit views are bounded; aggregate event counts
are queried separately and do not depend on the timeline limit.

Inbound Resend replies are associated only when the sending recipient uniquely
matches one outbound email in one tenant. Ambiguous replies are left unmatched
instead of attributed to the wrong campaign. SMS replies use the tenant-specific
number callback and the latest outbound message for that recipient.

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:RUN_LIVE_CAMPAIGNS="1"
.\.venv\Scripts\python.exe -m pytest tests/test_campaign_workflow_live.py -q -p no:cacheprovider
cd ..\frontend
npm test
npm run lint
npm run build
$env:PLAYWRIGHT_BROWSER_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
npm run test:e2e
```

The opt-in campaign integration test uses real local PostgreSQL and Temporal,
synthetic tenant/contact data, and mocked provider HTTP responses. It verifies
approval, scheduling, worker replacement, exactly one provider request, and actual
database analytics, then removes only its own synthetic organization. It sends
no real SMS or email. Live deliverability, DNS verification, Twilio registration,
and public incoming webhooks require external setup and must be checked separately.

In production, use durable Temporal/PostgreSQL storage, configure authenticated
Temporal networking/TLS as required by your deployment, run monitored workers,
retain OAuth encryption/signing keys, and deploy compatible workers when changing
workflow logic. Do not replace persistent services with ephemeral development
containers. See the [Temporal Python workflow documentation](https://docs.temporal.io/develop/python/workflows).

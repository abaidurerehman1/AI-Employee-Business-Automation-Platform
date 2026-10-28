# Phase 2 identity and tenant security audit

This audit extends the existing FastAPI authentication system and React workspace.
It preserves the existing Argon2id passwords, opaque server-side sessions, email
integration, tenant context, provider integrations and Phase 3–10 modules.

## Verified existing foundation

- Users, organizations and unique memberships; Admin, Manager and Employee roles.
- Argon2id password verification, hashed session and email-link credentials.
- HttpOnly/SameSite cookies, CSRF on authenticated mutations, controlled CORS.
- Email verification, recovery, invitations, multi-workspace switching.
- Tenant predicates in CRM, agent conversations, RAG, inbound, messaging and campaigns.
- Redis authentication throttling in staging/production: the configured per-IP,
  per-action limit applies to authentication POST requests and fails closed when
  Redis is unavailable. Development does not impose this production throttle.

## Gaps fixed

- Added profile, password, active-session list/revocation and session rotation APIs
  and connected account/security UI. Password changes revoke other sessions and
  outstanding reset links, rotate both cookie and CSRF token, and preserve the
  original absolute session expiration. Logout revokes the server-side record.
- Registration returns the same response for existing accounts. Login failures,
  forgot-password and verification resend retain generic responses. Passwords
  preserve significant whitespace; only human-readable names are trimmed.
- Verification/reset links are locked and rechecked under a consistent user-first
  lock order, preventing concurrent replay without issuance/consumption deadlocks.
- Added organization creation/rename, owner transfer with password confirmation,
  membership role/activation/removal and invitation list/revocation screens/APIs.
- Owner removal/demotion requires ownership transfer. Last active administrator
  changes are serialized under the organization lock. Mutations recheck current
  authority after acquiring that lock. Replaced, expired and revoked invitations,
  and invitations issued by users who lost authority, cannot grant access.
- Disabled memberships disappear from session workspace lists and immediately
  fail tenant authorization, including with an existing cookie.
- Reused the existing audit table for identity events. The administrator security
  feed returns event metadata without password hashes, session cookies or tokens.
- Centralized explicit permission grants in `app/core/permissions.py`; routes use
  reusable `require_permission`. Unknown roles/permissions fail closed. Employee
  membership explicitly grants shared CRM/knowledge reads and published-agent
  use; private agent conversations remain user-owned, and inbound conversations
  are restricted to the assigned employee. Campaign/integration management and
  bulk audience data remain manager/admin-only; campaign approval is admin-only.
- Temporal tool execution rechecks active requester and approver authority;
  conversation resume checks active membership. Queued outbound messages recheck
  the sender; campaign delivery also rechecks creator and approving administrator.
- Added password visibility controls with proper labels, accessible feedback,
  request loading states, expired-session and access-denied screens. Verification
  shares one request across React StrictMode effects so a one-use link is not
  accidentally consumed twice.
- Revoked invitations no longer appear as pending dashboard notifications.
- Accounts without memberships can still open settings and create a workspace;
  a removed selected workspace falls back to another authorized workspace.

## Migration

`20261028_0015_identity_management.py`, after `0014`, adds owner, membership-active
and invitation-revoked fields. Existing memberships remain active. Existing
organizations choose their earliest active administrator as owner. Legacy
organizations without an active administrator retain a null owner and require
an administrative data-recovery decision; the migration never grants access to
an unrelated user. Existing organizations/users/data are preserved.

## Verification commands

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:RUN_LIVE_IDENTITY="1"
$env:RUN_LIVE_FOUNDATION="1"
.\.venv\Scripts\python.exe -m pytest tests/test_identity_live.py tests/test_foundation_live.py -q -p no:cacheprovider
$env:RUN_LIVE_TEMPORAL="1"
$env:RUN_LIVE_CAMPAIGNS="1"
.\.venv\Scripts\python.exe -m pytest tests/test_temporal_live.py tests/test_crm_live.py tests/test_crm_writes_live.py tests/test_campaign_workflow_live.py -q -p no:cacheprovider
```

The concurrency test creates synthetic PostgreSQL records and removes them. The
foundation test migrates an isolated temporary database and checks Redis.
Provider calls and email sending in ordinary tests are simulated.

From `frontend`:

```powershell
npm run lint
npm run typecheck
npm run build
npm run test
$env:PLAYWRIGHT_BROWSER_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$env:RUN_LIVE_FOUNDATION="1"
npm run test:e2e
```

Browser tests cover account and team controls at 320, 768 and 1440 pixels,
password confirmation, verification replay protection, expired-session feedback,
existing CRM/campaign/inbound/widget/shell flows and live frontend/API CORS.

## Scope and operational limits

The session model intentionally remains an opaque-cookie design; no separate JWT
access/refresh subsystem or browser token storage was introduced. Session refresh
is available in account settings and credential changes rotate automatically.
The verified email is read-only in profile settings; changing an account's email
would require a separate verified-address-change workflow.

Future calling, calendars, property operations, tasks and finance modules must
declare explicit permissions and use the same tenant context, audit and approval
boundaries. This audit does not claim those future modules are implemented.

Production HTTPS/Secure cookies and working email-provider configuration still
need deployment-specific verification. Live inbox delivery, OpenAI quality,
Twilio and external provider credentials are not authenticated by mocked tests.
No production deployment or Git push is part of this audit.

## Executed audit results (28 October 2026)

- Backend regression suite: **104 passed, 24 opt-in tests skipped**.
- Combined live PostgreSQL/Redis/migrations/Temporal/CRM/campaign checks:
  **16 passed, 2 provider-dependent tests skipped**.
- Real Redis/Celery queue with unconfigured SMS provider: **1 passed**, no SMS sent.
- Frontend unit suite: **12 passed**; TypeScript, ESLint and production build passed.
- Migration `0015` is applied locally; `alembic check` reports no schema drift.
- Browser suite: **29 passed, 1 opt-in live-widget test skipped**; this includes
  the real running frontend/API connection. Account screenshots at 320/768/1440px
  were captured and mobile/desktop layouts visually reviewed.
- Frontend formatting checks passed. All seven Docker services are healthy.

Status: implemented and verified for local Phase 2 use. External inbox delivery
and production HTTPS verification remain deployment checks, not demonstrated by
the isolated identity tests. The backend emits an upstream Starlette/AnyIO
deprecation warning; it does not fail the tests.

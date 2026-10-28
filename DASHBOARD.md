# Phase 3 — Central dashboard and UI audit

This work extends the existing React/TypeScript/Vite frontend and FastAPI
application. It preserves the existing light visual identity, CSS tokens, SVG
icon system, authentication, agent chat, CRM, inbound, knowledge and campaign
modules. It adds no UI framework, external service or runtime dependency.

## Audit findings and implemented changes

The original overview only counted memberships and pending invitations. Its
navigation was component state without bookmarkable routes, every module waited
for the dashboard request, and notifications had no per-user read state. The
header lacked workspace search, a profile menu and an assistant entry point.

The shared shell now has grouped role-aware navigation, persistent desktop
collapse state, mobile navigation, breadcrumbs, profile/security access and
bookmarkable History API routes. Organization IDs in URLs are checked against
the signed-in user's memberships; organization switching resets record context.
Unknown application pages have an honest unavailable state. Only functional
modules appear in navigation.

Dashboard and module caches are invalidated across organizations and roles.
Dashboard requests are cancellable and keyed by organization, role and date
range. Search is debounced and cancels obsolete requests. Dashboard polling runs
every 15 seconds while the page is visible and refreshes on focus; member lists
refresh on workspace or membership changes. Module navigation does not refetch
the entire shell. A dashboard failure no longer blocks independent modules.
An unavailable session API shows a connection error and retry action.

## Actual metrics and date semantics

All production numbers come from tenant-filtered SQL queries:

| Metric | Meaning |
| --- | --- |
| Team members | Active workspace memberships belonging to active users |
| Active AI employees | Published employees with a published version |
| Contacts, leads, deals, campaigns | Records created in the selected UTC period |
| Lead chart | Leads created each UTC day, including true zero-count days |
| Lead stages | Current stage of leads created in the selected period |
| Deal value | Currently open deals created in the period, grouped by currency |
| Knowledge health | Current ready, queued/processing and failed document counts |
| Human follow-ups | Current human-support conversations; employees see assignments only |
| Pending approvals | Current pending tool/campaign requests; existing approval screens apply |
| Messages accepted/sent | Recorded accepted, sent or delivered messages in the period |
| Delivery issues | Recorded failed or uncertain messages created in the period |
| Recorded replies | Normalized provider `reply` events received in the period |

Activity filters offer 7, 30 and 90 days. Status-based counts such as active
employees, pending invitations, approvals and knowledge health include all dates,
as labeled. Deal value is pipeline value, not revenue; different currencies are
never summed. Accepted messages do not establish inbox delivery. Zero recorded
replies means no reply events were recorded, not that every provider supports
reply tracking.

Charts have accessible descriptions and a daily data table. Lead-stage links
apply CRM filters; search links open the actual CRM record, agent, campaign or
knowledge module. CRM and campaign record IDs are validated again by existing
tenant-aware APIs. Knowledge links highlight and scroll to the document.

## Notifications and activity

There is no second notification event stream. SQL projections reuse existing
invitations, agent requests, document failures, inbound handoffs, message delivery
issues and campaign states. Resolved alerts disappear from the current center;
existing audit/history records remain in their original modules.

Read receipts are per user and organization. Marking an alert read does not
approve, retry or resolve its underlying operation. Read mutations require CSRF
and validate that the current role can still see the source record. Another
user's receipt does not affect this user's unread count.

The center supports all/unread filters and database pagination, with at most 50
records per request. Counts are calculated before pagination. The dashboard
shows ten recent alerts and twenty recent activity records. Search returns at
most five matches per supported entity type. No customer bodies, tool arguments,
credentials or unrestricted audit metadata are exposed by these projections.

## Shared business configuration and assistant

Administrators can save industry focus, visible widgets and module navigation
for their organization. Supported focuses are general business, real estate,
holiday homes, clinics and service businesses. This configures one shared
dashboard; it does not create another application or enable unbuilt modules.
Hidden navigation is a presentation preference and never grants/revokes backend
permissions. Role checks remain authoritative.

The header assistant action opens the existing published AI employee chat.
Organization and source-page context are preserved. The server accepts only
known page names and explicitly instructs the model not to infer record data
from navigation context. Existing RAG citations, tools, approvals, sessions and
tenant boundaries are reused. Dashboard figures are not automatically inserted
into prompts, and no new autonomous-action capability is claimed.

Calling, appointments, property operations, tasks and finance are explicitly
unavailable. No invented bookings, financial figures, task counts or campaigns
are displayed for those future modules.

## UI and accessibility

The shared Button, Dialog, State and Table components remain in use. New reusable
primitives include Skeleton, Badge, Dropdown and Pagination. Forms retain labels,
validation, loading/error/success feedback and server-backed actions. Dialogs
have names and keyboard focus handling; the search shortcut is Ctrl/Cmd+K.
Mobile navigation supports Escape and restores focus. Profile controls support
keyboard interaction and outside-click dismissal. Charts have text/table
alternatives; loading animation respects reduced-motion preferences.

The existing light palette is retained. A partial dark theme was not added over
modules that do not yet have a complete dark design system. Sidebar and workspace
preferences store only identifiers/preferences in localStorage, never secrets.

## Migration and verification

Migration `20261028_0016_dashboard.py` follows `0015`. It adds
`dashboard_configurations` and `notification_receipts`, with tenant/user foreign
keys, uniqueness and lookup indexes. Existing operational data is preserved.

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:RUN_LIVE_FOUNDATION="1"
.\.venv\Scripts\python.exe -m pytest tests/test_foundation_live.py -q -p no:cacheprovider
$env:RUN_LIVE_TEMPORAL="1"
$env:RUN_LIVE_CAMPAIGNS="1"
$env:RUN_LIVE_IDENTITY="1"
.\.venv\Scripts\python.exe -m pytest tests/test_identity_live.py tests/test_temporal_live.py tests/test_crm_live.py tests/test_crm_writes_live.py tests/test_campaign_workflow_live.py -q -p no:cacheprovider
```

From `frontend`:

```powershell
npm run lint
npm run typecheck
npm run build
npm run test
npm run format:check
$env:PLAYWRIGHT_BROWSER_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$env:RUN_LIVE_FOUNDATION="1"
$env:RUN_LIVE_DASHBOARD="1"
npm run test:e2e
```

The live dashboard browser test signs in through the running frontend, checks
real PostgreSQL metrics, changes date filters, opens CRM records, searches and
persists notification read state across reload. It creates a temporary synthetic
organization and removes it afterward. It sends no email and makes no AI or SMS
provider calls. Other browser fixtures are controlled test data, not production
dashboard fallbacks. Screenshots cover 320, 768 and 1440 pixels.

Production HTTPS and external provider deliverability remain deployment-specific
checks. No Git push or production deployment is included in this audit.

## Executed results — 28 October 2026

| Verification | Actual result |
| --- | --- |
| Full backend regression suite | 110 passed; 24 opt-in tests skipped |
| Live PostgreSQL identity, Temporal, CRM and campaign regressions | 15 passed; 2 provider-dependent tests skipped |
| Fresh PostgreSQL migrations and Redis | 1 passed |
| Frontend unit tests | 14 passed |
| Complete Chromium browser suite | 39 passed; 1 opt-in live-widget test skipped |
| ESLint, TypeScript/production build, frontend formatting | Passed |
| New backend module lint and whitespace checks | Passed |
| Running migration / schema comparison | 0016 is head; no schema drift |
| Docker Compose / API readiness | All seven services healthy; readiness HTTP 200 |

The live browser journey passed against the running frontend and real API after
the final build. Controlled test records were removed. Dashboard screenshots at
320, 768 and 1440 pixels were captured; mobile and desktop layouts were visually
reviewed. Initial test-selector and typing failures were corrected and the
affected checks rerun successfully. An upstream Starlette/AnyIO deprecation
warning remains non-fatal.

**Phase 3 status: complete and verified locally.** There are no remaining local
Phase 3 blockers. This does not certify external delivery, production HTTPS or
future business modules; those retain their separate implementation and
deployment checks.

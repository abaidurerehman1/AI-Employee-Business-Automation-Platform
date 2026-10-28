# Phase 1 foundation audit

The existing modular application is preserved through Phase 10. This audit does
not implement future calling, appointment, property, task or finance features.
It verifies the shared infrastructure and extension boundaries they will use.

## Architecture and extension rules

| Concern | Existing shared implementation |
| --- | --- |
| Identity and tenancy | `api/dependencies.py`: authenticated sessions, tenant membership, roles and CSRF |
| Organization data | SQLAlchemy models with `organization_id`, tenant-filtered queries and relation validation |
| AI employees | Agent/version/conversation models and typed tool registry |
| Knowledge | Tenant-filtered PostgreSQL pgvector + full-text retrieval, document processing and citations |
| CRM | Company/contact/lead/deal services and `validate_links` for same-organization references |
| Communication | Existing Gmail, Resend and Twilio adapters; signed provider webhooks and suppressions |
| Execution | Temporal activities/workflows for durable actions; Celery/Redis for documents and individual messages |
| Approvals | Existing typed tool and campaign approval records; never execute from frontend permission checks alone |
| Audit | `core/audit.py` reuses existing audit storage; domain tool requests and approval snapshots retain their history |
| UI | Existing shell, shared buttons/dialogs/tables/states and `workspace.css` tokens |

Future calling, appointments, property operations, tasks, finance and reporting
should each add their own router/service/schema/models, mounted in `api/router.py`.
They must reuse authentication and tenant dependencies, attach organization IDs
to business records, validate cross-record organization ownership, and enforce
permissions in both APIs and background activities. Tenant IDs must come from
authenticated context or trusted stored work records, never unchecked request data.
Raw record IDs and foreign keys alone do not enforce tenant isolation.

Tenant isolation is enforced in application queries and permissions; this audit
does not claim PostgreSQL row-level security has been installed. Global identity
records and health/configuration metadata are intentionally outside tenant data.
The existing CRM relationship validator now also runs in the tool execution path.

Use `core/audit.record_audit` inside the mutation transaction for future modules.
Its physical table retains the legacy `campaign_audit` name to avoid creating a
second audit system; non-campaign modules leave `campaign_id` empty and record a
module name plus bounded, non-secret metadata. Provider events, tool execution
history and campaign approvals remain authoritative domain records, rather than
being replaced by a speculative general-purpose event bus.

Keep network calls and database writes in Temporal activities, use stable workflow
and idempotency keys, and persist approvals before consequential actions. Recheck
authorization and suppression at execution. Reuse provider adapters rather than
creating a second delivery stack. Gmail connections are organization-scoped;
installation-wide Resend/Twilio identities have the routing limits documented in
`CAMPAIGNS.md`. A future organization integrations module should extend these
boundaries before offering customer-owned credentials for those providers.

Industry-specific configuration belongs in agents, tools and domain workflows;
do not fork authentication, CRM or messaging for individual industries. Documents
are currently stored as bytes in PostgreSQL, so persistent database storage also
preserves their source files. No S3 or LiveKit dependency is introduced or required.

## Confirmed issues corrected

- Dependency failure previously returned HTTP 200. `/health` now returns 503 on
  failure; `/live` is dependency-independent; `/ready` checks migration head,
  pgvector, Redis and Temporal with bounded probe deadlines.
- ORM/database drift included nullable legacy timestamps and mismatched unique
  indexes/constraints. Migration `20261028_0014` fills missing timestamps and
  aligns definitions without removing uniqueness or deleting records. The existing
  PostgreSQL full-text GIN index is registered in metadata, not dropped.
- Concurrent startup migration runners serialize with a PostgreSQL advisory lock.
  Alembic handles percent-encoded credentials correctly and disposes connections.
- Settings reject unsafe production cookie/CORS/URL/database defaults and local
  self-send exceptions. Secrets are excluded from settings repr/error inputs.
  Optional providers remain optional; missing integrations are not invented.
- Production/staging authentication mutations reuse the existing Redis rate
  limiter (`AUTH_REQUESTS_PER_MINUTE`, per source IP and action). Login also rejects
  inactive accounts. Development workflows retain their existing behavior.
- The backend and workers run as UID 10001, connection pools/timeouts are bounded,
  and development ports bind to loopback. Celery writes its beat state in `/tmp`.
  Explicit frontend and worker health checks are installed.
- Requests have correlation IDs and structured metadata logs. Bodies, query
  strings and credentials are excluded. Unexpected responses are generic and
  readable from allowed frontend origins. Validation errors omit input values.
- The API client handles connection errors, invalid responses, no-content
  responses and bounded cancellation, allowing time for AI/tool continuations.
- Dialog heading IDs are unique, table scrolling is keyboard-focusable, mobile
  navigation handles focus/Escape, secondary text contrast is improved, and an
  application error boundary provides a recovery screen. Completed module layouts
  and product identity are retained. Tailwind/shadcn are not existing dependencies
  and were not introduced merely to replace functioning components.
- Frontend dependencies are pinned to the tested lockfile versions. Python runtime
  dependencies use `constraints.txt` captured from the tested runtime. Container
  base images and development Temporal are pinned by digest. Update these pins
  deliberately and rerun verification when applying security updates.
  Git attributes preserve LF shell
  scripts, and ignore rules cover environment variants and private key files.

## Development verification

Copy both environment examples before a fresh startup:

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
# Replace the root POSTGRES_PASSWORD before starting. Never overwrite an existing
# configured .env file using these copy commands.
docker compose up -d --build
docker compose ps
docker compose exec -T backend alembic current
docker compose exec -T backend alembic check
```

Use the root `.env` for Compose ports/database initialization; `backend/.env` is
the server-only provider/runtime configuration. Compose supplies internal service
addresses. If running Python directly, keep its DATABASE_URL synchronized with
root PostgreSQL settings, using URL-encoded credentials. Changing a PostgreSQL
environment password does not reset the password inside an existing data volume.
Make credential changes deliberately through PostgreSQL administration.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:RUN_LIVE_FOUNDATION="1"
.\.venv\Scripts\python.exe -m pytest tests/test_foundation_live.py -q -p no:cacheprovider
$env:RUN_LIVE_TEMPORAL="1"
$env:RUN_LIVE_CAMPAIGNS="1"
.\.venv\Scripts\python.exe -m pytest tests/test_temporal_live.py tests/test_crm_live.py tests/test_crm_writes_live.py tests/test_campaign_workflow_live.py -q -p no:cacheprovider
cd ../frontend
npm ci
npm test
npm run lint
npm run typecheck
npm run build
$env:PLAYWRIGHT_BROWSER_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$env:RUN_LIVE_FOUNDATION="1"
npm run test:e2e
```

The foundation integration test creates and removes only its own uniquely named
synthetic PostgreSQL database, runs migrations from empty to head twice, checks
schema drift/pgvector, and round-trips its own expiring Redis key. It requires
development database creation permission. The browser integration checks the real
Docker frontend/API, credentialed CORS, session response and readiness. Other
integration tests use synthetic tenants; campaign provider calls are mocked.
No real bulk messages are sent. Live OpenAI/provider tests remain opt-in.

## Production boundary

`compose.yaml` is explicitly a local development stack. Its persistent Temporal
start-dev SQLite server is not a production Temporal deployment. Named PostgreSQL,
Redis and Temporal volumes survive ordinary `up`/restart; never use `down -v` when
retaining data. Back up PostgreSQL and stable OAuth/signing keys separately.

`compose.production.yaml` is a **standalone application-services configuration**.
It connects to separately provisioned/private PostgreSQL+pgvector, Redis and
Temporal, and does not start development infrastructure. Copy
`production.env.example` to ignored `production.env`, and prepare a separate
`backend/.env.production` from the backend example. Set real service URLs and
credentials, HTTPS frontend/API origins, explicit API hosts (including localhost
for the health probe), `SECURE_COOKIES=true`, and production OAuth redirect URLs.
Keep frontend and API on the same site for the existing SameSite cookie policy.
Use `TEMPORAL_TLS`/`TEMPORAL_API_KEY` if required by the selected Temporal service.
Do not enable the local Gmail self-test flag in production.

Validate without starting or deploying anything:

```powershell
docker compose --env-file production.env -f compose.production.yaml config --quiet
```

Production migration application is an explicit release step; automatic migrations
are disabled in that file. Review and back up before the operator runs migrations.
Terminate HTTPS at a trusted proxy in front of the loopback application ports,
configure its upload limits/timeouts for documents and AI responses, and set
`FORWARDED_ALLOW_IPS` only to trusted proxy addresses. Never trust arbitrary
forwarded client-IP headers. Monitor worker and readiness failures; a local Temporal
heartbeat confirms the poller process/event loop, while API readiness verifies the
Temporal service itself. Do not scale the embedded Celery beat scheduler to multiple
copies without making the scheduler a singleton.

This audit validates local behavior and production configuration structure. It
does not claim a production deployment, public DNS/TLS provisioning, real provider
deliverability, external integration permissions, or every future business module
has been completed. The [FastAPI proxy guide](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)
explains the trusted proxy boundary.

## Executed audit results — October 28, 2026

| Check | Result |
| --- | --- |
| Backend regression suite | 88 passed; 21 opt-in tests skipped |
| Fresh PostgreSQL migrations, schema/pgvector and Redis | 1 integration test passed |
| Real PostgreSQL/Temporal tools, tenancy, approvals and campaign recovery | 12 passed; 2 live-AI tests skipped |
| Real Celery/Redis queue with unconfigured SMS | 1 passed; no SMS delivered |
| Frontend component/API/recovery/accessibility tests | 12 passed |
| Browser regressions, mobile/tablet/desktop and real frontend/API | 23 passed; 1 live-AI widget test skipped |
| Explicit TypeScript check, lint and production build | Passed |
| Alembic schema drift | No new upgrade operations detected |
| Runtime Python dependency pins and `pip check` | Exact versions match; no broken requirements |
| npm runtime vulnerability audit | Zero reported advisories at audit time |
| Development and production Compose validation | Passed; production was not launched |
| Docker startup and service health | All 7 local services healthy |

The initial schema-drift, health-status and lint issues were corrected and the
affected checks rerun. Skipped opt-in cases are not claimed as successful live
OpenAI/provider validation. There is no remaining blocker for the audited local
foundation; production still needs the explicitly configured infrastructure,
HTTPS/proxy setup and applicable external provider verification. No GitHub push
or production deployment was performed.

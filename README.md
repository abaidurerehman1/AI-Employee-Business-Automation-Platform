# AI Employee & Business Automation Platform

Phase 1 foundation for a multi-tenant AI workforce SaaS platform.

Audit reports: [Foundation](FOUNDATION.md), [Identity and tenant security](IDENTITY.md),
and [Central dashboard and UI](DASHBOARD.md).

## Stack

- React, TypeScript, and Vite
- FastAPI and Python 3.12
- PostgreSQL with SQLAlchemy and Alembic
- Redis
- Docker Compose

## Quick start

1. Copy `.env.example` to `.env`.
2. Copy `backend/.env.example` to `backend/.env`, then replace `POSTGRES_PASSWORD`
   in the root `.env` with a local development password. Keep the backend's local
   `DATABASE_URL` consistent if you also run Python outside Docker.
3. Start the stack:

   ```bash
   docker compose up --build
   ```

4. Open the frontend at <http://localhost:5173>.
5. Open API documentation at <http://localhost:8000/docs>.

The backend container applies Alembic migrations before starting the API. The
`GET /api/v1/health` verifies PostgreSQL and Redis. `/api/v1/live` checks the API
process; `/api/v1/ready` also verifies migration head, pgvector and Temporal.
Dependency/readiness failures return HTTP 503 instead of a misleading success.

## Authentication and organizations

Phase 2 provides secure multi-tenant identity and access management:

The current account, organization and authorization audit is documented in
[IDENTITY.md](IDENTITY.md), including migration `0015`, permission grants and test commands.

- Registration creates a user, organization, and Admin membership.
- Email verification is required before login.
- Passwords are hashed with Argon2.
- Sessions use random opaque tokens stored as hashes and sent in HttpOnly cookies.
- Password resets are single-use and revoke all existing sessions.
- Admins and Managers can invite members; Managers cannot grant Admin access.
- Tenant APIs require `X-Organization-ID` and validate membership before returning data.
- Authenticated mutations require the session CSRF token in `X-CSRF-Token`.

For Gmail delivery, set `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, and
`EMAILS_ENABLED=true` in `backend/.env`. Never commit the real `.env` file.

## Workspace dashboard

The dashboard shows actual organization membership counts, membership activity,
and pending invitation notifications. Pending invitation details and member
management navigation are available to Admins and Managers. The dashboard API
validates the selected organization against the signed-in user's memberships.
Other business metrics will appear when their underlying modules are built.

Browser layout tests use Playwright. Install a Chromium browser with
`npx playwright install chromium`, then run `npm run test:e2e` from `frontend`.
To use an existing browser, set `PLAYWRIGHT_BROWSER_PATH` to its executable.

## AI employee development

Set `OPENAI_API_KEY` in `backend/.env` to use the playground and recreate the
backend container. Agent configurations are stored as immutable versions;
publishing selects a version, and editing creates a new draft version. The
playground uses the latest version and keeps each user's conversations private.
The initial tool registry contains a read-only UTC clock. Its permission and
approval settings are enforced by the server for both manual and model-requested
calls. Pending requests appear in the playground and never run before approval.
For the UTC clock, approval or rejection is recorded in the original conversation
as an assistant message. Existing requests created before conversation linking
and manually requested tools remain standalone.

## Local development

Backend:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

## Tests

```bash
cd backend
pytest

cd ../frontend
npm run lint
npm run test
npm run build
```

## Phase 1 completion checklist

- [x] Frontend and backend folders
- [x] React + TypeScript + Vite frontend
- [x] FastAPI backend
- [x] PostgreSQL and Redis services
- [x] SQLAlchemy and Alembic migration
- [x] Environment configuration and Docker Compose
- [x] Health endpoint and typed frontend API client
- [x] Automated frontend/backend checks

# Website support widget

In **Inbound chat**, an administrator or manager selects a published AI employee,
saves the widget, and copies the displayed embed snippet to a website. Visitors
can chat, submit their contact details and qualification information, or request
a person. The inbox lets managers assign a conversation and lets the assigned
employee reply. Public chat does not have access to internal agent tools.

For deployment, the widget's frontend and API URLs must be publicly reachable
over HTTPS. Configure `VITE_API_URL` at frontend build time and include the widget
frontend origin in backend `CORS_ORIGINS`; localhost URLs work only on the same
computer. Public endpoint rate limiting requires Redis and uses the request peer
address. A reverse proxy needs a trusted, correctly configured client-IP setup
for per-visitor limits. Visitor tokens expire after seven days.

The signed webhook accepts JSON with `event_id`, `name`, `email`, `enquiry`, and
optional `budget` and `timeline`. Send `X-Timestamp` as Unix seconds and
`X-Signature` as the lowercase hex HMAC-SHA256 of the exact bytes
`timestamp + "." + request_body`, using the secret shown in widget settings.
Requests older than five minutes are rejected; event IDs are deduplicated per site.
Keep the webhook secret private. It is stored in the application database, so
protect database access and backups accordingly.

## Messaging setup

The Messaging screen lets workspace managers save templates, preview messages,
queue individual emails or SMS messages, and manage suppression lists. The
configured sender is shared by the installation. Set `RESEND_API_KEY` and
`RESEND_FROM_EMAIL` in `backend/.env`; the sender domain must be verified in
Resend. `RESEND_REPLY_TO` is optional. Set `MESSAGING_PUBLIC_BASE_URL` to the
public HTTPS API origin and `MESSAGING_UNSUBSCRIBE_SECRET` to a long random secret
before sending email. Without these settings, email fails closed. Point Resend's
signed webhook at `/api/v1/messaging/webhooks/resend` and set
`RESEND_WEBHOOK_SECRET` from the provider dashboard. Email replies sent directly
to a Gmail reply-to address remain in Gmail; use a Resend receiving address and
webhook to bring replies into this application.

To enable SMS later, configure `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and
`TWILIO_FROM_NUMBER`. Configure the Twilio incoming-message webhook to
`/api/v1/messaging/webhooks/twilio/{organization_id}` on the public API origin.
The same endpoint accepts delivery callbacks and opt-out replies. Use a webhook
configuration that routes messages to the correct organization. The application
does not automatically retry uncertain provider outcomes; check those in the
provider dashboard before taking further action. The default hourly queue limit
is 100 messages per organization and can be changed with `MESSAGING_HOURLY_LIMIT`.

For Gmail, enable the Gmail API in Google Cloud and add the exact
`GOOGLE_REDIRECT_URI` value (locally,
`http://localhost:8000/api/v1/messaging/gmail/callback`) to the OAuth client's
authorized redirect URIs. Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and a
stable Fernet `OAUTH_ENCRYPTION_KEY` to `backend/.env`, restart the services,
then select **Messaging → Connect Gmail** and authorize the intended account.
If the OAuth app is in testing mode, add the account as a test user. The Gmail
connection is scoped to the workspace and takes precedence over Resend for that
workspace. Refresh tokens are encrypted with `OAUTH_ENCRYPTION_KEY`; back up that
key securely because changing or losing it requires users to reconnect. Gmail
also needs the public unsubscribe URL described above. For local testing only,
`MESSAGING_PUBLIC_BASE_URL=http://localhost:8000` permits sending solely to the
connected Gmail address; other recipients require a publicly reachable HTTPS URL.
Delivery is accepted by
Gmail but final delivery status and Gmail replies are not synchronized by this
connection. Revoking account permissions in Google is separate from disconnecting
the workspace in this app.

## Marketing campaigns

Phase 10 setup, verification, provider limitations and operator instructions: [CAMPAIGNS.md](CAMPAIGNS.md).

Foundation architecture, environment separation, audit results and verification:
[FOUNDATION.md](FOUNDATION.md).

# AI Employee & Business Automation Platform

Phase 1 foundation for a multi-tenant AI workforce SaaS platform.

## Stack

- React, TypeScript, and Vite
- FastAPI and Python 3.12
- PostgreSQL with SQLAlchemy and Alembic
- Redis
- Docker Compose

## Quick start

1. Copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD` with a local development password.
3. Start the stack:

   ```bash
   docker compose up --build
   ```

4. Open the frontend at <http://localhost:5173>.
5. Open API documentation at <http://localhost:8000/docs>.

The backend container applies Alembic migrations before starting the API. The
dashboard calls `GET /api/v1/health`, which verifies the API, PostgreSQL, and
Redis connections.

## Authentication and organizations

Phase 2 provides secure multi-tenant identity and access management:

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
npm install
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


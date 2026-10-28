#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
  alembic upgrade head
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"


FROM python:3.12-slim@sha256:6b25cbe6577518889d553cdd5a5da97d259348d8f6e45b527dd731caaba27a07

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh .

RUN chmod +x docker-entrypoint.sh
RUN groupadd --gid 10001 employee && useradd --uid 10001 --gid employee --no-create-home employee
USER employee

EXPOSE 8000

CMD ["./docker-entrypoint.sh"]


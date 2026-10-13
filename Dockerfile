# ── Builder ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


# ── Runtime ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ ./app/
COPY frontend/ ./frontend/
COPY seed.py .

# Writable dir for SQLite + local uploads (used when S3 / Postgres aren't configured)
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app

USER appuser

# Free hosts (Render, Koyeb, Cloud Run…) inject $PORT; default 8000 locally.
ENV PORT=8000
EXPOSE 8000

# One worker: fits 512 MB free instances and avoids SQLite write contention.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]

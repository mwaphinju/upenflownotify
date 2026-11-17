# Upenflow Notify

Upenflow Notify receives order-fulfilment messages from Service A, evaluates versioned mapping rules, and prepares customer SMS messages for delivery through a Sender ID gateway. This first increment implements email OTP access, rule management and simulation, signed inbound ingestion, and idempotent rule processing. Gateway delivery, analytics, notifications search, settings, and the remaining account-management workflows are subsequent feature milestones.

## Run locally with Docker Compose

Prerequisites: Docker Desktop with the Linux container engine enabled.

1. Copy `.env.example` to `.env` and set unique values for the first admin password, OTP pepper, inbound API key, and HMAC secret.
2. Run `docker compose up --build`.
3. Open `http://localhost:5173` to sign in. OTP messages are available in MailHog at `http://localhost:8025`.
4. Open `http://localhost:8000/docs` for the interactive API.

PostgreSQL persists in the `postgres-data` volume. The API applies the Alembic migration before startup. Redis/RQ processes inbound matching outside the HTTP request; when `UPENFLOW_REDIS_URL` is unset, local tests and development use FastAPI's in-process background task.

To add the demo mapping rules after the first admin is seeded, run:

```powershell
docker compose exec api python -m app.seed
```

## Backend tests

```powershell
py -3.12 -m pip install -r backend/requirements.txt
py -3.12 -m pytest -c backend/pyproject.toml backend/tests
```

The tests use isolated SQLite databases and do not require Docker, Redis, or SMTP.

## Service A webhook

Set `UPENFLOW_SERVICE_A_API_KEY` and `UPENFLOW_SERVICE_A_HMAC_SECRET`. Sign the exact request body with HMAC-SHA256 using `timestamp + "." + body` as the signed bytes. Send the Unix timestamp, API key, and lowercase hex digest in `X-Service-A-Timestamp`, `X-Service-A-Key`, and `X-Service-A-Signature`. Timestamps outside five minutes are rejected.

```bash
timestamp="$(date +%s)"
body='{"message_id":"fulfilment-1001","recipient":"0712345678","text":"Order 1001 dispatched","order_ref":"1001"}'
signature="$(printf '%s' "$timestamp.$body" | openssl dgst -sha256 -hmac "$UPENFLOW_SERVICE_A_HMAC_SECRET" -hex | awk '{print $NF}')"
curl -i http://localhost:8000/api/inbound/service-a \
  -H "Content-Type: application/json" \
  -H "X-Service-A-Key: $UPENFLOW_SERVICE_A_API_KEY" \
  -H "X-Service-A-Timestamp: $timestamp" \
  -H "X-Service-A-Signature: $signature" \
  --data "$body"
```

The API persists each unique `message_id` and returns `202 Accepted`. Matching rule versions and rendered SMS content are retained with the inbound record.

## Service B delivery reports and replies

Delivery reports at `POST /api/dlr/service-b` use the same signed-webhook scheme as Service A: set `UPENFLOW_SERVICE_B_DLR_API_KEY` and `UPENFLOW_SERVICE_B_DLR_HMAC_SECRET`, and send `X-Service-B-Key`, `X-Service-B-Timestamp`, and `X-Service-B-Signature` headers (HMAC-SHA256 over `timestamp + "." + body`).

If Service B forwards inbound SMS replies, point it at `POST /api/inbound/service-b-reply` with an `X-Service-B-Key` header matching `UPENFLOW_SERVICE_B_REPLY_API_KEY`. A reply whose text is exactly `STOP` (case-insensitive) adds the sender to the blocklist automatically.

## Background scheduler

The API process runs an in-process scheduler (`UPENFLOW_ENABLE_SCHEDULER=true` by default, interval `UPENFLOW_SCHEDULER_INTERVAL_SECONDS`) that re-attempts queued messages once quiet hours or a pause lifts, checks for Service A silence and Service B error-rate spikes, sends the monthly-budget alert and daily/monthly email summaries, and purges data past the configured retention window. Disable it on any secondary API replica to avoid duplicate alerts.

## Security notes

- No public registration endpoint exists. The first Super Admin is seeded from environment variables.
- Passwords use Argon2id. OTPs and session tokens are stored as keyed hashes or hashes, never as plaintext.
- Use HTTPS and set `UPENFLOW_COOKIE_SECURE=true` outside local development.
- API secrets and SMTP credentials belong in environment variables, not source control.
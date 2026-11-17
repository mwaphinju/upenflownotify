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

## Database migrations

Schema changes are tracked with Alembic (`backend/migrations/versions`). Revision `0001_initial_schema`
bootstraps the schema from the current `app/models.py` via `create_all`, which means a fresh database is
always up to date after that single revision — later revisions only need to handle databases created
*before* a given model change shipped, so every later revision checks the database's actual state (via
`sqlalchemy.inspect`) before altering anything, making it a safe no-op on a fresh install and a real
migration on an older deployment. Follow this pattern for new revisions; don't assume revision 0001
reflects a frozen historical schema.

Apply migrations with `docker compose exec api alembic upgrade head` (the `api` container also runs this
automatically on startup). Roll back one revision with `alembic downgrade -1`.

## Backups and retention

- **Postgres backups**: snapshot the `postgres-data` volume or run `pg_dump` on a schedule appropriate to
  your recovery objectives (e.g. `docker compose exec postgres pg_dump -U notify notify > backup.sql`).
  Test restores (`psql -U notify notify < backup.sql` against a fresh volume) periodically — an untested
  backup is not a backup.
- **Automatic data retention**: the background scheduler purges `inbound_messages` past
  `retention.message_retention_days` and `audit_log` rows past `retention.audit_log_retention_days`
  (Settings → Data retention; defaults 180 and 730 days). Only messages in a terminal status are purged;
  anything still `Queued`/`Sending` is left alone regardless of age.
- **Manual deletion**: there is currently no UI for deleting an individual customer's message history on
  request. If a deletion/export request arrives (e.g. a data-subject request under applicable privacy law),
  it must be handled directly against the database for now — flagged under Remaining risks below.

## Production frontend build

`frontend/Dockerfile` has two targets. `docker-compose.yml`'s `web` service builds the `dev` target (the
Vite dev server), which is **not suitable for production** — it is meant for local development only. For a
real deployment, build the `prod` target instead, which compiles the static build and serves it via nginx
with security headers and SPA routing:

```bash
docker build --target prod -t upenflow-notify-web:prod ./frontend
docker run -p 80:80 upenflow-notify-web:prod
```

That container serves only static assets; `/api` calls still need to reach the `api` service, so put both
behind the same reverse proxy/ingress in production (or point the SPA at the API's own public URL).

## Security notes

- No public registration endpoint exists. The first Super Admin is seeded from environment variables.
- Passwords use Argon2id. OTPs and session tokens are stored as keyed hashes or hashes, never as plaintext.
- Use HTTPS and set `UPENFLOW_COOKIE_SECURE=true` outside local development.
- API secrets and SMTP credentials belong in environment variables, not source control.
- The API sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and
  `Strict-Transport-Security` on every response (the last one only takes effect once served over HTTPS).
  The production frontend (nginx `prod` target) sets the same headers plus a `Content-Security-Policy`.
- No CORS middleware is configured, by design: the frontend and API are intended to sit behind the same
  origin (via a reverse proxy) or to be accessed through the dev proxy locally — cookie-based auth with
  `SameSite=Strict` would not work across a cross-site origin anyway. If you ever serve the frontend from a
  genuinely different origin than the API, you will need to add explicit CORS configuration and reconsider
  the cookie `SameSite` setting.
- Dependencies are scanned in CI (`pip-audit`, `npm audit`) on every push/PR — see `.github/workflows/ci.yml`.
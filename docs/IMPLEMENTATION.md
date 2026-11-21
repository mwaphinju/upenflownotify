# Upenflow Notify — Implementation Document

This document is for a developer picking up this codebase for the first time. It describes
what has been built, how it fits together, and the reasoning behind the non-obvious decisions.
It is a snapshot as of **2026-11-21**; read `git log` for anything more recent than this file.

For day-to-day operational instructions (running locally, webhook contracts, backups), see the
top-level [`README.md`](../README.md) — this document focuses on *how the system is built*, not
*how to operate it*.

## 1. What this system does

Upenflow Notify sits between two external services:

- **Service A** pushes order-fulfilment events as inbound webhook messages (`"Order 1001
  dispatched"`, etc.).
- **Service B** (Onfon Media) is the SMS gateway that actually delivers text messages to
  customers' phones, and pushes delivery reports back.

In between, Upenflow Notify evaluates **versioned mapping rules** (regex/contains/starts-with
match on the inbound text → an SMS template with placeholders) to decide *whether* a message
should become an outbound SMS, *what* it should say, and *which Sender ID* it goes out under —
then runs it through a safety pipeline (blocklist, duplicate suppression, per-recipient
throttling, quiet hours, segment limits, a global on/off switch) before handing it to Service B.

The product also provides the operational surface around that: an admin UI for managing rules,
watching message status and costs on a dashboard, configuring the gateway/billing/safety
settings, managing users and sessions, and getting alerted (by email) when something looks wrong
(Service A has gone silent, Service B's error rate spiked, the SMS budget or gateway balance is
low).

## 2. Current scope (as of the commits below)

Done:
- Email + OTP two-factor login, session management, password reset/change, admin user
  management (invite, force-reset, role, deactivate, revoke sessions).
- Mapping rule CRUD with versioning (every edit snapshots the prior version; versions are
  restorable), priority-ordered matching, and a "test a message against current rules" simulator.
- Signed, idempotent Service A ingestion (`POST /api/inbound/service-a`) — HMAC-SHA256 over
  `timestamp + "." + body`, replayed `message_id`s are deduped, matching runs in the background
  (Redis/RQ if configured, else FastAPI's in-process `BackgroundTasks`).
- The full outbound delivery pipeline (see §5): rule render → safety checks → Service B send →
  retry with backoff → delivery-report reconciliation.
- A direct "manual send" endpoint that bypasses rule matching but goes through the same delivery
  pipeline — a stand-in for exercising delivery until more upstream sources than Service A exist.
- Service B (Onfon) integration: `SendBulkSMS`, `Balance`, push-DLR webhook
  (`GET /api/dlr/service-b[/{token}]`), and inbound SMS-reply webhook with automatic `STOP`
  handling into the blocklist.
- Dashboard with KPIs/cost charts, Notifications search/export (CSV/PDF), audit log via
  `AuditLog` rows written alongside every state-changing action.
- Background scheduler (in-process `asyncio` task, not a separate process): re-wakes queued
  messages, Service A silence / Service B error-rate / budget / low-balance alerting, daily and
  monthly email summaries, and data retention purging.
- Material 3-styled React/Vite frontend covering all of the above, with a collapsible sidebar and
  auto-refreshing views.
- CI: backend pytest, `pip-audit`, `bandit`; frontend `npm audit`, `tsc`, build; a Playwright
  end-to-end smoke test against a full `docker compose` stack.

Explicitly **not yet built** (per the README's framing of this as "this first increment"):
notifications search/settings/account-management workflows beyond what's listed above, and any
UI for per-customer data deletion (a data-subject deletion request currently has to be handled
directly against the database — see README "Backups and retention").

## 3. Architecture at a glance

```
Service A ──HMAC webhook──▶ FastAPI (api) ──▶ Postgres
                                 │                 ▲
                                 ▼                 │
                          Redis/RQ queue ──▶ worker (rq worker, same image as api)
                                 │
                                 ▼
                          Service B (Onfon) ──push-DLR (plain GET)──▶ FastAPI (api)

                          React/Vite (web) ──REST, cookie session──▶ FastAPI (api)
                          MailHog ◀── OTP / alert emails (dev only; real SMTP in prod)
```

- **`api`** (FastAPI, Python 3.12) — all HTTP routes, the delivery pipeline's synchronous parts,
  and the in-process background scheduler (`asyncio.create_task` in the app's `lifespan`).
- **`worker`** — the *same backend image*, just started with `rq worker --url redis://... notifications`
  instead of `uvicorn`. It executes `deliver_queued_message_job` / `process_queued_inbound_message`
  jobs enqueued by the API when `UPENFLOW_REDIS_URL` is set. Only one process type to build/deploy.
- **`postgres`** — single source of truth; Alembic-migrated.
- **`redis`** — RQ broker only (not used for caching, sessions, or rate limiting).
- **`mailhog`** — local-dev SMTP relay + web UI, so OTP/alert emails never require real SMTP
  credentials in development.
- **`web`** — Vite dev server in `docker-compose.yml` (see README "Production frontend build" for
  the separate nginx-served `prod` target used in real deployments).

Why Redis/RQ is optional rather than required: tests and local development can run with
`UPENFLOW_REDIS_URL` unset, in which case `enqueue_delivery`/`enqueue_inbound` fall back to
FastAPI's `BackgroundTasks` and everything runs in-process, single-worker. This keeps the test
suite free of a Redis dependency while still exercising the real pipeline functions.

## 4. Backend module map (`backend/app/`)

| Module | Responsibility |
|---|---|
| `main.py` | App factory (`create_app`), startup (schema creation when `auto_create_schema`, first-admin seeding, scheduler task), security/logging middleware, router registration. |
| `config.py` | `Settings` (pydantic-settings, `UPENFLOW_`-prefixed env vars, `.env`-loaded). |
| `database.py` | SQLAlchemy engine/session-factory builders, `Base`, `get_db` FastAPI dependency. |
| `models.py` | All ORM models (see §6). |
| `security.py` | Argon2id password hashing, OTP generation/hash/compare, opaque-token hashing for sessions/challenges. |
| `auth.py` | `/api/auth/*` — login → OTP → session cookie flow, resend/verify, logout(-all), DB-backed rate limiting (`AuthRateLimit`), forgot/set password. |
| `accounts.py` | `/api/me*`, `/api/admin/users*` — profile, sessions list/revoke, password change (OTP-gated), admin user CRUD/invite/force-reset. |
| `rules.py` + `rule_matching.py` | Mapping rule CRUD, versioning/restore, reordering, the `/api/rules/test` simulator. `rule_matching.py` is the pure matching/rendering/segment-counting logic with no DB/FastAPI dependency, shared by `rules.py` (editor-time validation) and `delivery.py` (runtime matching). |
| `delivery.py` | The whole inbound→outbound pipeline: `/api/inbound/service-a` ingestion, `process_inbound_message` (rule matching), `deliver_queued_message` (the guarded send pipeline, see §5), `/api/messages/manual-send`, and the Redis/`BackgroundTasks` enqueue switch. |
| `service_b.py` | `ServiceBAdapter` (Onfon `SendBulkSMS`/`Balance` HTTP calls, `ServiceBError` with a `retryable` flag), the push-DLR webhook, and the inbound SMS-reply webhook (auto-blocklists `STOP` replies). |
| `configuration.py` | `/api/settings` — gateway/billing/safety/limits/monitoring/retention config, stored as one JSON blob (`SystemSetting.key == "configuration"`) with a `with_defaults`/`DEFAULTS` merge so old records survive new fields being added; gateway secrets are symmetric-encrypted at rest (`encrypt_secret`/`decrypt_secret`), never returned decrypted to the frontend. |
| `sending.py` | `/api/settings/sending` — the global on/off/paused switch read by the delivery pipeline. |
| `blocklist.py` | `/api/blocklist` CRUD (soft-delete via `removed_at`). |
| `messages.py` | `/api/messages*`, `/api/dashboard*` — search, CSV/PDF export, per-customer timeline, resend, KPI dashboard. |
| `analytics.py` | KPI/cost computation shared by the dashboard and the scheduler's email summaries. |
| `monitoring.py` | The scheduler's actual checks (see §7) — silence/error-rate/budget/low-credit alerts, daily/monthly summaries, retention purge, queued-message re-wake. |
| `alerts.py` | `send_alert` — formats and emails the alert types above to `configuration.alert_emails`. |
| `email.py` | Thin SMTP wrapper (`smtplib`) used by both `auth.py` (OTP/account emails) and `alerts.py`. |
| `ratelimit.py` | Per-process, in-memory, per-IP token-bucket limiter for the three public webhook endpoints (deliberately *not* the DB-backed `AuthRateLimit` pattern — see README "Security notes" for why). |
| `phone.py` | Kenyan mobile number normalization (`normalize_kenyan_mobile`) and network detection from prefix tables. |
| `reports.py` | CSV/PDF export rendering helpers used by `messages.py`. |
| `logging_config.py` | Structured (JSON-ish, `extra={"fields": {...}}`) logging setup. |
| `seed.py` | `python -m app.seed` — demo mapping rules for a fresh environment. |

## 5. The delivery pipeline in detail (`delivery.py`)

This is the most intricate part of the system, so it's worth walking through explicitly —
particularly because it was recently refactored (`c9385ad "Decompose deliver_queued_message into
named guard functions"`) specifically to make it readable and testable.

1. **Ingestion** (`receive_service_a`): verify HMAC signature + timestamp window (±5 min) →
   normalize the recipient → insert `InboundMessage(status="Received")` → enqueue
   `process_inbound_message` (idempotent: a replayed `message_id` hits the unique constraint,
   which is caught and treated as "already accepted").

2. **Rule matching** (`process_inbound_message`): walk enabled+disabled rules in priority order,
   first match wins. Stamps the message with `rule_id`, `rule_version_id` (the specific
   `MappingRuleVersion` active at match time — so a later rule edit doesn't retroactively change
   what an already-matched message is attributed to), `sender_id`, and the rendered text. No
   match → `status="Unmapped"`. Matched but rule disabled → `status="Suppressed"`. Otherwise
   `status="Queued"` (or `"Skipped"` if the global switch is `stopped`), and
   `deliver_queued_message` runs immediately.

3. **The guarded send** (`deliver_queued_message` + its `_check_*` helpers): each check is a
   small function that raises `_DeliveryHalted(status, reason)` to short-circuit the pipeline and
   write a terminal (or re-queueable) status. In order: decrypt gateway credentials → rule still
   enabled → global switch still on → not inside quiet hours → recipient still normalizes →
   segment count within limit → sender ID still allowed → not blocklisted → not a duplicate
   (same rendered text to the same recipient within `safety.duplicate_window_minutes`) → not over
   the per-recipient hourly throttle → (if `test_mode`) on the test allowlist. This order matters:
   cheaper/config-only checks run before anything that queries message history, and
   credential decryption happens first because every other check is pointless if the gateway
   isn't configured.

   If `safety.test_mode` and `safety.fake_gateway` are both set, the message is marked `Sent`
   without calling Service B at all — this is what lets the Playwright smoke test and local
   development exercise the full UI without live SMS credentials.

4. **Sending with retries** (`_send_with_retries`): re-checks rule/global-switch state on *every*
   attempt (not just once) before calling `ServiceBAdapter.send`, because state can change while
   a retry is sleeping. Backoff is `min(30 * 2**attempt, 600)` seconds. A `ServiceBError` marks
   `retryable=False` for anything Onfon would never succeed at on retry (e.g. bad credentials);
   retryable errors are retried up to `limits.retry_attempts` (default 3) before going `Failed`.

5. **Delivery reports** (`service_b.py`'s `/service-b[/{token}]`): Onfon's push-DLR is an
   unauthenticated plain `GET` (see README for why — it's their actual contract, not a design
   choice made here) that always returns `200 OK` even for an unrecognized `messageId`, so a
   stale/duplicate report can never make this endpoint look unhealthy to monitoring.
   `errorCode` `0`/`000` → `Delivered`, anything else → treated as a failed delivery.

Everything in step 3 is a **pure function given its inputs** (`InboundMessage`, the
`configuration` JSON, a `Session`) — that's deliberate, so each guard can be unit-tested in
isolation (`backend/tests/test_sending.py`) without constructing an entire HTTP request.

## 6. Data model (`models.py`)

- `User` / `LoginChallenge` / `UserSession` / `AccountToken` / `AuthRateLimit` — auth and account
  lifecycle. Passwords are Argon2id; OTP codes, session tokens, challenge tokens, and reset tokens
  are all stored as **hashes** (`token_hash`/`otp_hash`), never plaintext, so a DB leak alone
  doesn't yield usable credentials.
- `MappingRule` / `MappingRuleVersion` — the rule itself plus an append-only version history
  (`UniqueConstraint("rule_id", "version")`); editing a rule bumps `version` and snapshots the
  prior state as JSON, which is what makes `/api/rules/{id}/versions/{version}/restore` possible.
- `InboundMessage` — one row per Service A event *and* per manual send, carrying the full
  lifecycle: received → matched (`rule_id`/`rule_version_id`/`sender_id`/`rendered_text`) →
  queued/sent/delivered/failed, plus cost accounting (`segments`, `rate_per_segment_kes`,
  `cost_kes`) and the provider's own message ID for DLR reconciliation.
- `AuditLog` — generic `(actor_id, action, entity, entity_id, before, after, reason, ip_address)`
  row written alongside essentially every state-changing admin/rule/message action.
- `SystemSetting` — a key/JSON-value table used as a lightweight settings store for three
  independent blobs: `"configuration"` (gateway/billing/safety/etc, see `configuration.py`),
  `"sending"` (the global switch, see `sending.py`), and `"monitoring_state"` (scheduler's
  dedup markers — see §7). Not a generic key-value cache; each key has a specific, documented
  shape maintained by its owning module.
- `BlocklistEntry` — soft-deleted (`removed_at`) phone blocklist.

Migrations live in `backend/migrations/versions/`. Per the README: revision `0001_initial_schema`
bootstraps from `models.py` via `create_all`, so **every later revision must check the database's
actual state via `sqlalchemy.inspect` before altering anything** — it has to be a no-op on a fresh
install and a real migration only on a pre-existing older deployment. Follow this pattern; don't
assume `0001` is a frozen historical schema.

## 7. Background scheduler (`monitoring.py`)

Runs as an `asyncio` task inside the `api` process (`enable_scheduler`, default on; disable on
secondary API replicas to avoid duplicate alerts — there's no distributed lock). Each tick
(`scheduler_interval_seconds`, default 60s) calls `run_once`, which:

1. Re-attempts anything still `Queued` (covers messages that were queued during quiet hours or a
   paused switch and need to be woken once that lifts).
2. Runs each alert check (`check_service_a_silence`, `check_service_b_health`,
   `check_budget_alert`, `check_low_credit`) — each is dedup-guarded via a marker stored in
   `monitoring_state` (e.g. `service_a_alert_for`, `budget_alert_month`) so the same condition
   doesn't re-alert every tick.
3. Sends the daily (08:00 local) and monthly (1st, 08:00 local) email summaries, also marker-
   guarded against local timezone (`configuration.timezone`, default `Africa/Nairobi`).
4. Purges data past retention (`purge_old_data`) — at most once per day, and only terminal-status
   messages/audit rows (see README "Backups and retention" for the exact policy).

## 8. Frontend (`frontend/src/`)

React + Vite + TypeScript. `App.tsx` owns the pre-authentication flow (login → OTP → session,
plus the standalone `/?token=...` set-password page) and renders `Workspace.tsx` once a session
exists. `Workspace.tsx` is a thin shell (app bar, collapsible `Sidebar`, role-gated view switch)
over the actual feature pages in `src/pages/`:

| File | View |
|---|---|
| `DashboardPage.tsx` | KPIs, cost charts |
| `NotificationsPage.tsx` | Message search, export, resend |
| `RulesPage.tsx` | Rule CRUD, versions, simulator |
| `BlocklistPage.tsx` | Blocklist management |
| `UsersPage.tsx` | Admin user management (super admin only) |
| `SettingsPages.tsx` (`SettingsRouter`) | Gateway/billing/safety/monitoring settings (super admin only) |
| `AccountPages.tsx` (`AccountRouter`) | Profile / Security / Sessions (split out of a single "My Account" page — see git history) |

This was previously a single monolithic `Workspace.tsx`; it was split into these feature modules
(`77930f5`) to keep each page independently readable. If you're adding a new top-level view,
follow that pattern: add a page component under `src/pages/`, wire it into `Workspace.tsx`'s view
switch and `Sidebar.tsx`'s nav list, gate it by `role` the same way the existing views do (role
checks currently live inline in `Workspace.tsx`, e.g. `currentUser.role === 'super_admin'`).

`api.ts` / `hooks.ts` / `types.ts` hold the shared fetch wrapper, data-fetching hooks, and
TypeScript types respectively. Session auth is a plain `httpOnly`, `SameSite=Strict` cookie
(`credentials: 'include'` on every request) — there's no token in JS-accessible storage.

## 9. Security posture (see also README "Security notes")

- No public registration; the only way to create a `User` is the first-admin seed at startup or
  an existing super admin inviting one.
- Argon2id for passwords; everything else credential-shaped (OTPs, session/challenge/reset
  tokens) is hashed before storage.
- Gateway API credentials (Onfon API key/Client ID/Access key) are symmetric-encrypted at rest in
  the `configuration` JSON blob using `secret_encryption_key` (falls back to `otp_pepper` if
  unset — see `_decrypt_gateway_credentials`), and are never sent back to the frontend decrypted.
- The three public webhook endpoints get a per-process, per-IP in-memory rate limit
  (`ratelimit.py`) as defense-in-depth on top of their HMAC/token auth — deliberately *not* the
  DB-backed pattern auth uses, to avoid a DB round-trip on every webhook call (20 msg/s NFR).
  Know its limits: resets on restart, doesn't share state across replicas, sees the proxy's IP if
  behind one.
- No CORS middleware, by design — frontend and API are meant to share an origin via a reverse
  proxy (or the dev proxy locally); cookie `SameSite=Strict` wouldn't work cross-site anyway.
  Adding a genuinely separate frontend origin later means revisiting both of these.
- CI runs `pip-audit`/`npm audit` on every push/PR, plus `bandit` against the backend; suppress a
  confirmed false positive inline with `# nosec <code> - <reason>`, never globally.

## 10. Testing

- `backend/tests/` (pytest, isolated SQLite per test — no Docker/Redis/SMTP needed): one file per
  functional area (`test_auth.py`, `test_rules.py`, `test_sending.py` for the delivery pipeline
  guards, `test_service_b_adapter.py`, `test_ratelimit.py`, etc). Run with
  `py -3.12 -m pytest -c backend/pyproject.toml backend/tests`.
- `frontend/e2e/smoke.spec.ts` (Playwright): the one end-to-end test, run against a *real*
  `docker compose` stack — logs in with password + OTP fetched from MailHog's REST API, lands on
  the dashboard, navigates to Rules, signs out. It's a smoke test (stack boots, auth works,
  navigation renders), not feature coverage — don't mistake a green run here for full regression
  coverage of a page's logic.
- CI (`.github/workflows/ci.yml`) has separate `backend` and `frontend` jobs, plus an `e2e` job
  that brings up the full stack with disposable credentials and runs the Playwright smoke test
  against it.

## 11. Running it locally

See the README's "Run locally with Docker Compose" section — summary: copy `.env.example` to
`.env`, set the required secrets, `docker compose up --build`. Frontend at `:5173`, API docs at
`:8000/docs`, MailHog (OTP emails) at `:8025`. `docker compose exec api python -m app.seed` adds
demo mapping rules. The `api` container's startup command runs `alembic upgrade head` before
`uvicorn` — migrations are never a separate manual step in this setup.

## 12. Known gaps / where to look before extending

- No UI for per-customer data deletion (a privacy/data-subject deletion request currently means
  a direct database operation) — flagged in the README, not yet built.
- The in-memory webhook rate limiter (`ratelimit.py`) is single-process and resets on restart —
  fine for today's single-API-replica deployment; revisit if you ever run multiple API replicas
  behind a load balancer and need it to actually hold under a distributed flood.
- The scheduler has no distributed lock — running more than one API replica with
  `enable_scheduler` on will double-send alerts/summaries. Disable it
  (`UPENFLOW_ENABLE_SCHEDULER=false`) on every replica but one.
- `SystemSetting` is a JSON blob store, not a generic cache — before adding a fourth key to it,
  check whether what you're storing really fits the "owning module maintains its own documented
  shape" pattern the existing three keys follow, or whether it deserves a real table.

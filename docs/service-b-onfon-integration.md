# Service B integration — Onfon Media

Reference for the real Onfon Media integration implemented in `backend/app/service_b.py` and
`backend/app/monitoring.py`. All three pieces below are live, tested, and verified against a real
Onfon account.

## Sending — SendBulkSMS

`POST https://api.onfonmedia.co.ke/v1/sms/SendBulkSMS`

Headers: `Content-Type: application/json`, `AccessKey: <access key>`

```json
{
  "SenderId": "UPENFLOW",
  "IsUnicode": false,
  "MessageParameters": [{ "Number": "254712345678", "Text": "..." }],
  "ApiKey": "...",
  "ClientId": "..."
}
```

- `ScheduleDateTime` is never sent — every send is immediate.
- `IsUnicode` reflects whether the rendered text needs Unicode encoding, derived from the same
  GSM-7/Unicode detection already used for segment counting (`sms_segments()`), not re-detected.
- One `MessageParameters` entry per call — the app sends message-by-message, not true batches.
- Success: `{"ErrorCode": 0, "Data": [{"MessageId": "..."}]}` → `Data[0].MessageId` is stored as
  `provider_message_id` for later DLR matching.
- `ErrorCode != 0` is treated as a permanent failure (not retried) — Onfon doesn't publish a
  failure-code table, so there's no way to tell transient codes from permanent ones yet.
- HTTP 5xx / network / timeout errors are retried per the existing retry/backoff policy; a 4xx or
  an `ErrorCode != 0` on a 2xx response is not.

## Balance — checking SMS credit

`GET https://api.onfonmedia.co.ke/v1/sms/Balance?ApiKey={ApiKey}&ClientId={ClientId}`

Same `AccessKey` header as sending. Response:
`{"ErrorCode": 0, "Data": [{"PluginType": "SMS", "Credits": "KSh7578560.8000"}]}`.

`Credits` is parsed by stripping everything but digits and `.` (handles the `KSh` prefix) into a
`Decimal`. Checked periodically by the background scheduler — see Settings > Monitoring & Alerts
for the enable toggle, check interval, and low-balance threshold — and on demand via the "Check
now" button there (`POST /api/settings/balance/check`).

## Delivery reports — push DLR

Onfon pushes DLRs as a **plain GET**, no signature or auth header, to a URL you register in their
dashboard, and does **not retry** if your server is unreachable at the time:

```
GET https://yourdomain/api/dlr/service-b?doneDate={doneDate}&submitDate={submitDate}&errorCode={errorCode}&shortMessage={shortMessage}&status={status}&messageId={messageId}&mobile={mobile}
```

- `messageId` is matched against `provider_message_id`. An unmatched ID (stale, purged by
  retention, or a report that arrived twice) still gets a `200 OK` — Onfon's own requirement is to
  respond within 10 seconds regardless, and since there's no retry on their side, returning
  anything else risks Onfon marking the endpoint unhealthy for no benefit to us.
- `errorCode` of `0`/`000` → `Delivered`; anything else → `Failed`, with `shortMessage` (if any)
  recorded as the error. No published error-code table exists to refine this further.
- `doneDate`/`submitDate` format isn't documented, so they're accepted but not parsed into a
  timestamp — `delivered_at` uses the server's own receipt time instead of trusting an unverified
  date format from the request.
- Optional hardening: set `UPENFLOW_SERVICE_B_DLR_TOKEN` and register
  `https://yourdomain/api/dlr/service-b/<token>` with Onfon instead of the bare path. A
  query-string secret (`?token=...`) isn't used because Onfon's example builds the callback URL as
  `base + "?" + their_own_params`, which would corrupt a query string already present on the base
  URL — a path segment is safe regardless of how naively that concatenation is implemented.
- **This only works once the API has a public URL.** A local `docker compose` setup has nothing
  Onfon can reach, so DLRs will never arrive in that environment — `Sent` is as far as a message's
  status will get locally; `Delivered`/`Failed` only start appearing once deployed somewhere with
  a real, internet-reachable domain registered with Onfon.

# Service B integration — Onfon Media SendBulkSMS

Replace the generic placeholder `ServiceBAdapter` in `backend/app/service_b.py` with a concrete
implementation of Onfon Media's bulk SMS API, sending one message per call (immediate delivery,
no scheduling).

## Endpoint

`POST https://api.onfonmedia.co.ke/v1/sms/SendBulkSMS`

Headers: `Content-Type: application/json`, `AccessKey: <access key>`

Body:

```json
{
  "SenderId": "UPENFLOW",
  "IsUnicode": false,
  "MessageParameters": [{ "Number": "254712345678", "Text": "..." }],
  "ApiKey": "...",
  "ClientId": "..."
}
```

- Omit `ScheduleDateTime` entirely — all sends are immediate.
- `IsUnicode` must reflect whether the rendered text needs Unicode encoding (the app already
  computes GSM-7 vs Unicode via `sms_segments()` for segment counting — reuse that, don't
  re-detect).
- One `MessageParameters` entry per call (the app sends message-by-message, not true batches).

## Response

Success: `{"ErrorCode": 0, "ErrorDescription": "Success", "Data": [{"MobileNumber": "...", "MessageId": "..."}]}`

- `ErrorCode == 0` → success; take `Data[0].MessageId` as the provider message ID.
- `ErrorCode != 0` → treat as a permanent failure (not retried) until Onfon's error-code table is
  available to classify which codes are transient.
- HTTP 5xx or network/timeout errors → retryable (existing adapter retry/backoff logic already
  handles this at the call-site level; the adapter itself should raise the existing `ServiceBError`
  with `retryable=True`/`False` as appropriate, same contract as today).

## Configuration changes needed

Gateway settings currently store `base_url`, `username`, `api_key` (encrypted), `default_sender_id`,
`allowed_sender_ids`. Onfon needs three credential values instead of `username` + `api_key`:

- `api_key` (existing field, reused for Onfon's `ApiKey`)
- `client_id` (new)
- `access_key` (new — sent as the `AccessKey` header)

`username` is unused by this provider and should be removed from the schema rather than kept dead.
All three credential fields should be encrypted at rest and masked in the Settings UI, consistent
with how `api_key` is already handled.

## Acceptance

- A message with GSM-7-only text sends with `IsUnicode: false`; one containing non-GSM-7 characters
  sends with `IsUnicode: true`.
- `Data[0].MessageId` is stored as `provider_message_id` and later matched by the existing DLR
  endpoint.
- A non-2xx HTTP response or network error is retried per the existing retry/backoff policy; a 2xx
  response with `ErrorCode != 0` is not retried and the message is marked `Failed` with
  `ErrorDescription` recorded.
- Existing idempotency (dedup on Service A's `message_id`) and the existing DLR endpoint are
  unaffected — this change is scoped to the outbound send call only.

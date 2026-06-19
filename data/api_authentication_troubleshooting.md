# API Authentication Troubleshooting

## Authentication scheme
All API requests must include a bearer token in the `Authorization` header:

```
Authorization: Bearer <your_api_key>
```

Tokens are issued from **Developer Settings > API Keys** and are valid for
12 months from creation unless manually revoked.

## Common error codes

### 401 Unauthorized
Returned when the token is missing, malformed, expired, or revoked.

Checklist:
- Confirm the header is exactly `Authorization: Bearer <token>` (note the
  required space after `Bearer`).
- Confirm the token has not expired. Expiry date is visible in the
  developer dashboard next to each key.
- Regenerate the key if it was rotated or revoked by another team member.

### 403 Forbidden
The token is valid but lacks the scope required for the requested
endpoint. Each API key is scoped to one or more of: `read:inventory`,
`write:inventory`, `read:billing`, `admin`. Update the key's scopes in
Developer Settings, or generate a new key with the correct scope.

### 429 Too Many Requests
Rate limit exceeded. Default limits are 100 requests/minute per key.
Implement exponential backoff and retry. The response includes a
`Retry-After` header indicating the wait time in seconds.

### 500 Internal Server Error on auth endpoints
If `/v1/auth/token` returns a 500 with no other context, this typically
indicates a transient outage on our identity service rather than a problem
with your integration. Check the status page before retrying.

## OAuth2 client credentials flow (enterprise customers)
Enterprise customers using OAuth2 should request a token from
`/oauth/token` using the `client_credentials` grant type. Tokens expire
after 1 hour and must be refreshed programmatically — they are not
intended to be hardcoded.

## Webhook signature verification failures
See `integration_webhook_setup.md` for HMAC signature verification, which
is a separate authentication layer from API key auth.

## When to escalate
If 401 errors persist after confirming a valid, unexpired, correctly
scoped token, and the status page shows no incident, escalate with the
following details: API key prefix (first 8 characters only — never share
the full key), endpoint called, timestamp, and the full response body.

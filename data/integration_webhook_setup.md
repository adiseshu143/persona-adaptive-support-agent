# Integration Webhook Setup Guide

## Overview
Webhooks let your system receive real-time events (inventory updates,
order status changes, payment confirmations) instead of polling our API.

## Setting up a webhook endpoint
1. Go to Developer Settings > Webhooks > Add Endpoint
2. Enter a publicly reachable HTTPS URL (HTTP is not supported)
3. Select the event types you want to subscribe to
4. Save — a signing secret is generated and shown once. Store it securely.

## Verifying webhook signatures
Every webhook request includes an `X-Signature` header computed as an
HMAC-SHA256 hash of the raw request body, using your signing secret as the
key. Always verify this signature before processing the payload to confirm
the request genuinely originated from us:

```python
import hmac, hashlib

def verify_signature(payload_body, signature_header, secret):
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

Reject any request where the signature does not match, and do not log the
raw signing secret.

## Common configuration errors

### Webhook marked "Failing" in dashboard
Your endpoint returned a non-2xx status code on the last 5 consecutive
attempts. Check your endpoint's logs around the failure timestamps shown
in the dashboard.

### Events not arriving at all
- Confirm the endpoint is publicly reachable (not behind a VPN or
  localhost tunnel that isn't currently running)
- Confirm the event type you expect is actually selected in the
  subscription configuration
- Check your firewall isn't blocking our outbound IP ranges, listed on the
  status page under "Network Allowlist"

### Duplicate events received
Webhooks follow an at-least-once delivery guarantee. Your endpoint should
be idempotent — use the `event_id` field to deduplicate on your side
rather than assuming each event_id arrives exactly once.

## Retry policy
Failed deliveries are retried with exponential backoff over 24 hours
(5 attempts total: immediately, +5m, +30m, +2h, +12h). After 24 hours with
no successful delivery, the event is marked as permanently failed and
will not be retried automatically — use the "Replay Event" button in the
dashboard if needed.

## When to escalate
If signature verification fails consistently despite using the secret
exactly as shown at creation time, this may indicate the secret was
rotated without your integration being updated — escalate with the
endpoint ID and a recent failed delivery ID so we can check rotation
history on our side.

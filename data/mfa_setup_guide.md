# Multi-Factor Authentication (MFA) Setup Guide

## Why enable MFA
MFA adds a second verification step at login, drastically reducing the
risk of account takeover even if your password is leaked. We strongly
recommend it for any account with billing or admin permissions.

## Supported methods
- Authenticator app (TOTP) — Google Authenticator, Authy, 1Password, etc.
- SMS code (fallback only; not available in all countries)
- Hardware security key (FIDO2/WebAuthn) — Enterprise plans only

## Setting up TOTP (recommended)
1. Go to Account Settings > Security > Two-Factor Authentication
2. Select "Authenticator App"
3. Scan the displayed QR code with your authenticator app
4. Enter the 6-digit code shown in the app to confirm setup
5. Save the 10 backup codes shown — each can be used once if you lose
   access to your authenticator app

## Locked out because of lost MFA device
If you no longer have access to your authenticator app and have used all
backup codes:
1. Click "Lost your device?" on the MFA prompt during login
2. This starts an identity verification flow requiring your account email
   plus one additional verification item (recent invoice number or last 4
   digits of the card on file)
3. Verification is reviewed by our security team and is **not instant** —
   allow up to 24 hours. This delay is intentional and cannot be expedited
   even with an active subscription, because it exists specifically to
   prevent account takeover via social engineering.

## Changing MFA method
You can switch between TOTP, SMS, and hardware key under Security
settings at any time, provided you can currently authenticate. Switching
methods invalidates previously issued backup codes — generate a fresh
set after switching.

## Enterprise: enforcing MFA org-wide
Admins on Enterprise plans can require MFA for all members under
Admin Console > Security Policies > Require MFA. Existing sessions are
not immediately terminated; enforcement applies at next login.

## When to escalate
Any MFA recovery request that cannot be resolved through the standard
"Lost your device?" flow — for example, the account email itself is also
inaccessible — must be escalated, since this touches account-security
verification that automated support is not permitted to complete.

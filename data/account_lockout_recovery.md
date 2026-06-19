# Account Lockout Recovery Guide

## Overview
Accounts are temporarily locked after 5 consecutive failed login attempts
within a 15-minute window. This is a security measure and does not mean
your account has been compromised.

## How to recover a locked account

1. Wait 15 minutes. Locks are lifted automatically and no support ticket
   is required for a standard lockout.
2. If you need immediate access, use **Account Recovery** on the login
   screen and verify via the email or phone number on file.
3. If recovery emails are not arriving, check spam/junk folders and confirm
   `no-reply@ourapp.com` is allow-listed.
4. If you still cannot log in after 30 minutes, the lockout may be linked
   to a flagged IP address (common on shared corporate networks or VPNs).
   Try a different network and attempt login again.

## Lockout caused by suspicious activity (Error Code: E402)

Error code **E402** indicates the lockout was triggered by our fraud
detection system rather than a standard failed-login lock. This can happen
after:

- A login attempt from a new country within a short time of a login from
  your usual location
- Multiple password reset requests in a short period
- A password that matches a known breached-credentials list

For E402 lockouts, self-service recovery is disabled for 24 hours as a
precaution. During this window:

- The account owner will receive an email with a one-time verification
  link valid for 24 hours.
- If the email is not received, this requires escalation to a human agent
  who can verify identity manually and lift the restriction.

## Preventing future lockouts

- Enable multi-factor authentication (see `mfa_setup_guide.md`)
- Use a password manager to avoid repeated failed attempts
- Keep your recovery email and phone number up to date in Account Settings

## Related documents
- `password_reset_guide.pdf`
- `mfa_setup_guide.md`

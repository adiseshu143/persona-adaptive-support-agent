# Data Export Guide

## What can be exported
- Inventory records (CSV, XLSX)
- Order history (CSV)
- Audit logs (CSV, JSON) — Enterprise plans only
- Full account data export (ZIP archive of all of the above) for GDPR /
  data portability requests

## Standard export (CSV/XLSX)
1. Go to the relevant module (Inventory, Orders, etc.)
2. Click Export > choose format
3. Exports under 50,000 rows are generated instantly and download directly
4. Exports over 50,000 rows are processed asynchronously; you'll receive
   an email with a download link valid for 7 days

## Full account data export (GDPR / data portability)
1. Go to Account Settings > Privacy > Request Data Export
2. This generates a complete archive of your account's data
3. Processing takes up to 72 hours per our data protection obligations
4. The download link expires after 7 days for security

## Export failures
If an export job shows "Failed" status:
- Check that no filters applied to the export reference deleted fields
  (common after a recent schema change to custom fields)
- Retry once — transient failures during high load are the most common
  cause
- If it fails twice with the same error code, escalate with the export
  job ID shown in Export History

## Important note on data deletion requests
Requests to permanently delete account data (as opposed to exporting it)
are not handled through this export flow and are not something automated
support can execute directly, since deletion is irreversible and requires
identity verification plus a mandatory waiting period under our data
retention policy. These requests should always be escalated.

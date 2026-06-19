# Database Integration Troubleshooting

## Supported integration methods
- Native connectors: PostgreSQL, MySQL, Snowflake
- Generic JDBC connection for other SQL databases (Enterprise only)
- Scheduled CSV/SFTP drop for legacy systems without direct connectivity

## Connection errors

### "Connection refused" or timeout
- Confirm your database accepts inbound connections from our published
  IP allowlist (Developer Settings > Integrations > Outbound IPs)
- Confirm the port specified matches your database's listener port
  (default 5432 for Postgres, 3306 for MySQL)
- If using a cloud-managed database (RDS, Cloud SQL), confirm the
  security group / firewall rule includes our IP range

### "Authentication failed"
- Confirm the database user has not had its password rotated since the
  connector was configured
- Confirm the user has at least `SELECT` privileges on the target schema;
  write integrations additionally require `INSERT`/`UPDATE`

### Sync runs but no new rows appear
- Check the "Last Successful Sync" timestamp in the integration dashboard
- Confirm your incremental sync key (usually `updated_at` or an
  auto-incrementing ID) is actually changing on new/modified rows —
  syncs rely on this column to detect changes
- Confirm the source table's row-level security policies (if any) don't
  filter out rows from the service account used for syncing

## Internal errors during sync (Error Code: E501)
E501 indicates a schema mismatch was detected mid-sync — typically a
column type changed on the source database after the integration was
first configured. Sync pauses automatically rather than risk writing
malformed data. Re-run schema detection from the integration settings
page to resolve.

## When to escalate
Persistent internal errors during sync that are NOT resolved by schema
re-detection, especially if accompanied by partial or corrupted data
already written to the destination, should be escalated immediately with
the sync job ID and the exact error code, since this can affect data
integrity.

# Service Outage Response Policy

## Status page
All incidents, whether full outages or partial degradations, are posted to
the public status page within 15 minutes of detection, including affected
components and an initial impact assessment.

## Severity levels

**Sev 1 — Full outage**: core product unusable for all customers.
Target: status update every 30 minutes until resolved.

**Sev 2 — Partial degradation**: a specific feature (e.g. webhooks,
exports, search) is slow or failing for a subset of customers.
Target: status update every 60 minutes.

**Sev 3 — Minor issue**: cosmetic or low-impact issue with a workaround
available. Target: resolution noted in the next release notes, no
real-time status updates required.

## What support agents (human and AI) should do during an active incident
1. Check the status page before treating a customer-reported issue as
   account-specific — if a Sev 1 or Sev 2 incident is already posted,
   reference the existing incident rather than troubleshooting from
   scratch.
2. Do not promise a specific resolution time beyond what is stated on the
   status page, even under pressure from a frustrated or executive-level
   customer. Overpromising resolution times that are then missed damages
   trust more than acknowledging uncertainty.
3. For business-impact questions ("what is the operational impact, when
   will this be fixed"), provide the latest official status page summary
   and the next scheduled update time rather than speculating.

## Post-incident
A post-incident summary is published within 5 business days of
resolution for any Sev 1 incident, including root cause and prevention
steps. Customers on Enterprise plans with an SLA may be eligible for
service credits per their contract — this determination is made by the
account management team, not through self-service support.

## Escalation during outages
Any conversation that references an ongoing incident and asks about
compensation, SLA credits, or contractual remedies should be escalated to
a human agent, since these require account-specific contract review.

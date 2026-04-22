# Security

Remembr V1 is designed around scoped access, soft deletion, and operator visibility rather than a flat memory bucket.

## Auth model

- Human users authenticate through `/auth/*` and receive JWTs.
- SDKs and adapters should use API keys from `/api-keys`.
- Every request carries an effective org scope. Optional team, user, and agent scope narrow it further.

## Scoping

- Organization isolation is the baseline control.
- Sessions are created inside the caller's writable scope.
- Search and history queries inherit that scope automatically.
- Structured tags help organization but do not replace security boundaries.

## Row-level isolation

Remembr uses database-level scoping to prevent cross-tenant reads. Application code resolves the request scope, and the database session enforces the final isolation boundary.

## PII

V1 does not promise automatic PII detection or redaction. Teams should:

- Avoid storing secrets in memory content
- Keep sensitive IDs in metadata only when necessary
- Prefer scoped API keys over shared org-wide keys
- Use deletion workflows for data subject requests

PII automation and policy tooling are forward-looking concerns, not solved by V1 alone.

## Encryption

- TLS should terminate at your ingress or platform edge
- Managed Postgres and Redis should use encrypted transport where available
- At-rest encryption depends on your database and volume provider

## Soft deletes and purge

- Deletes are soft by default
- Soft-deleted memories disappear from normal reads immediately
- Hard delete permanently removes a specific episode
- Scheduled purge jobs clear expired soft-deleted data

## Auditability

- `request_id` is returned on API responses
- Admin UI surfaces memory and session inspection for local operations
- Webhook deliveries expose event-level outcomes
- Export and diff endpoints support operator review workflows

## Audit logs

Remembr V1 has partial auditability through structured logs, webhook delivery records, request IDs, and deletion state. It is not yet a full compliance audit trail product.

## Operational checklist

- Rotate API keys on ownership changes
- Keep `SECRET_KEY` out of source control
- Restrict `/admin` to trusted environments
- Run Postgres with `pgvector`
- Back up the database before large-scale deletes


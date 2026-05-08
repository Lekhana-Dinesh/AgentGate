# Deployment Hardening

## Goal

This build adds a production-minded hardening baseline without requiring heavy local infrastructure:

- strict production config validation
- safer CORS and response headers
- deeper readiness checks
- safer demo and seed behavior
- guardrails around unsafe audit-export destinations

## Production env checklist

Set these explicitly in non-development deployments:

- `AGENTGATE_ENV=production` or `staging`
- `AGENTGATE_SECRET_KEY` to a long random secret
- `AGENTGATE_PUBLIC_APP_URL` to the externally reachable dashboard origin
- `AGENTGATE_PUBLIC_API_URL` to the externally reachable API origin
- `AGENTGATE_CORS_ORIGINS` to explicit browser origins
- `AGENTGATE_AUTH_SESSION_MODE`
- `AGENTGATE_SCIM_TENANT_TOKEN_REFS` if SCIM is enabled
- `AGENTGATE_KEY_PROVIDER`
- `AGENTGATE_JOB_DISPATCH_MODE`
- `AGENTGATE_JOB_BROKER`
- `AGENTGATE_RATE_LIMIT_PROVIDER`

Recommended:

- For `AGENTGATE_KEY_PROVIDER=env`:
  - `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` or `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF`
- For `AGENTGATE_KEY_PROVIDER=aws_kms`:
  - `AGENTGATE_AWS_REGION`
  - `AGENTGATE_AWS_KMS_KEY_ID`
- `AGENTGATE_RATE_LIMIT_ENABLED=true`
- `AGENTGATE_RATE_LIMIT_PROVIDER=redis`
- `AGENTGATE_RATE_LIMIT_SCIM_LIMIT` and `AGENTGATE_RATE_LIMIT_SCIM_WINDOW_SECONDS` sized for your IdP
- `AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS=false`
- `AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS=false`
- For browser-focused production deployments:
  - `AGENTGATE_AUTH_SESSION_MODE=cookie`
  - `AGENTGATE_COOKIE_SECURE=true`
  - `AGENTGATE_COOKIE_SAMESITE=lax`
  - `AGENTGATE_CSRF_ENABLED=true`
  - `AGENTGATE_COOKIE_DOMAIN` only when cross-subdomain cookie sharing is required

## Startup validation

Outside `development` and `test`, AgentGate now rejects:

- weak or default JWT signing secrets
- wildcard or malformed CORS origins
- localhost or private-network CORS origins
- non-HTTPS public URLs unless `AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS=true`
- missing env-provider payload-protection keys
- missing AWS KMS region or key ID when `AGENTGATE_KEY_PROVIDER=aws_kms`
- unsupported key providers
- `AGENTGATE_JOB_BROKER=redis` without `AGENTGATE_REDIS_URL`
- `AGENTGATE_RATE_LIMIT_PROVIDER=redis` without `AGENTGATE_REDIS_URL`
- `AGENTGATE_RATE_LIMIT_PROVIDER=in_memory` outside development/test unless `AGENTGATE_ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true`
- `AGENTGATE_AUTH_SESSION_MODE=cookie` outside development/test without `AGENTGATE_COOKIE_SECURE=true`
- `AGENTGATE_AUTH_SESSION_MODE=cookie` outside development/test with `AGENTGATE_CSRF_ENABLED=false`
- `AGENTGATE_COOKIE_SAMESITE=none` without `AGENTGATE_COOKIE_SECURE=true`
- `AGENTGATE_SCIM_TENANT_TOKEN_REFS` entries that are literal tokens instead of env-backed or secret-ref-style references

When `AGENTGATE_AWS_KMS_ENDPOINT_URL` is configured:

- it must be a valid `http` or `https` URL
- outside development/test, localhost or private-network endpoints are rejected
- outside development/test, `https` is required unless `AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS=true`

Audit export destination URLs are also validated on create and update:

- `endpoint_url` must be `http` or `https`
- embedded credentials, queries, and fragments are rejected
- localhost and private-network destinations are rejected outside development/test unless `AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS=true`

The default demo seed is now blocked outside development/test unless `AGENTGATE_ALLOW_DEMO_CREDENTIALS=true`.

## Health and readiness

- `GET /health` stays lightweight and only reports basic process availability.
- `GET /ready` checks the database and returns safe component status for jobs, key management, and enabled integrations.
- `GET /ready` now also reports the configured rate-limit provider and Redis reachability without exposing Redis connection details.
- when `AGENTGATE_KEY_PROVIDER=aws_kms`, `GET /ready` reports the KMS provider status, active key ref, readiness, warnings, and safe AWS region metadata; if the configured KMS key is unavailable, readiness returns `503`
- In containerized deployments, prefer `/ready` for health checks that gate traffic.

## Reverse proxy and TLS

Recommended deployment shape:

1. Put AgentGate behind a TLS-terminating reverse proxy or ingress.
2. Expose only the proxy to the public internet.
3. Set `AGENTGATE_PUBLIC_APP_URL` and `AGENTGATE_PUBLIC_API_URL` to the external HTTPS origins seen by browsers and OIDC providers.
4. Keep `/metrics` internal if possible, even though it only exposes aggregate counters and gauges.
5. If you enable cookie mode, keep the dashboard and API on origins that match your cookie and CORS plan.
6. If you enable SCIM, treat it as machine-to-machine auth only. Do not route SCIM through browser session flows.

## Security headers

The API now adds:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Content-Security-Policy` on normal API responses

`/docs` and related OpenAPI UI assets are intentionally exempt from the strict CSP so the FastAPI docs still render locally.

## Container notes

The compose stack now:

- uses `/ready` for the API container health check
- exposes the new hardening env vars
- preserves easy local defaults

For self-hosted production-style deployments, use the separate `compose.prod.example.yml` profile and the operator docs:

- `docs/operations/self-hosted-deployment.md`
- `docs/operations/production-runbook.md`
- `docs/operations/production-readiness-checklist.md`

For real deployments:

- use a strong `AGENTGATE_SECRET_KEY`
- supply a real env-provider payload encryption key or switch to AWS KMS explicitly
- move off localhost URLs
- run a dedicated worker when `AGENTGATE_JOB_DISPATCH_MODE=worker`
- if you use AWS KMS, grant only `kms:DescribeKey`, `kms:GenerateDataKey`, and `kms:Decrypt` on the configured key
- if you use SCIM, inject one strong bearer token per tenant through environment or a secret manager workflow, not a git-tracked file

## Remaining limitations

- the Redis-backed limiter uses fixed windows, not adaptive or token-bucket algorithms
- readiness does not verify that an external worker process is alive
- readiness does not resolve or probe every tenant-specific integration or connector
- readiness validates safe AWS KMS availability but does not perform a full end-to-end encrypt/decrypt transaction before first use
- audit-export private-network validation is based on explicit localhost/private hosts, not DNS resolution of arbitrary hostnames
- self-hosted production deployment is currently Compose-based guidance, not Kubernetes, Helm, or Terraform
- cookie mode remains stateless and is not a substitute for a fuller enterprise session-management platform
- SCIM token rotation and inventory are still deployment-managed rather than tenant-admin-managed

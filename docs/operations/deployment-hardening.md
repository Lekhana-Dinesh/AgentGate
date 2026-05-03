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
- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` or `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF`
- `AGENTGATE_JOB_DISPATCH_MODE`
- `AGENTGATE_JOB_BROKER`

Recommended:

- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY`
- `AGENTGATE_RATE_LIMIT_ENABLED=true`
- `AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS=false`
- `AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS=false`

## Startup validation

Outside `development` and `test`, AgentGate now rejects:

- weak or default JWT signing secrets
- wildcard or malformed CORS origins
- localhost or private-network CORS origins
- non-HTTPS public URLs unless `AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS=true`
- missing payload-protection keys
- unsupported key providers
- `AGENTGATE_JOB_BROKER=redis` without `AGENTGATE_REDIS_URL`

Audit export destination URLs are also validated on create and update:

- `endpoint_url` must be `http` or `https`
- embedded credentials, queries, and fragments are rejected
- localhost and private-network destinations are rejected outside development/test unless `AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS=true`

The default demo seed is now blocked outside development/test unless `AGENTGATE_ALLOW_DEMO_CREDENTIALS=true`.

## Health and readiness

- `GET /health` stays lightweight and only reports basic process availability.
- `GET /ready` checks the database and returns safe component status for jobs, key management, and enabled integrations.
- In containerized deployments, prefer `/ready` for health checks that gate traffic.

## Reverse proxy and TLS

Recommended deployment shape:

1. Put AgentGate behind a TLS-terminating reverse proxy or ingress.
2. Expose only the proxy to the public internet.
3. Set `AGENTGATE_PUBLIC_APP_URL` and `AGENTGATE_PUBLIC_API_URL` to the external HTTPS origins seen by browsers and OIDC providers.
4. Keep `/metrics` internal if possible, even though it only exposes aggregate counters and gauges.

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

For real deployments:

- use a strong `AGENTGATE_SECRET_KEY`
- supply a real payload encryption key
- move off localhost URLs
- run a dedicated worker when `AGENTGATE_JOB_DISPATCH_MODE=worker`

## Remaining limitations

- the current rate limiter is in-memory, not distributed
- readiness does not verify that an external worker process is alive
- readiness does not resolve or probe every tenant-specific integration or connector
- audit-export private-network validation is based on explicit localhost/private hosts, not DNS resolution of arbitrary hostnames

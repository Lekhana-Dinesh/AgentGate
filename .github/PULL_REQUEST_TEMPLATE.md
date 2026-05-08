## Summary

- What changed?
- Why does this change belong in AgentGate?

## Verification

- [ ] `cd apps/api && python -m compileall app`
- [ ] `cd apps/api && python -m pytest app/tests -q -o cache_dir=.tmp/pytest_cache`
- [ ] `cd apps/web && npm run build`
- [ ] `docker compose config`
- [ ] I added or updated tests for security-critical behavior where applicable.
- [ ] I did not commit `.env` files, tokens, cookies, database files, or other secrets.

## Security Checklist

- [ ] I did not weaken tenant isolation, gateway governance, or approval controls.
- [ ] I did not expose decrypted payloads, raw secrets, or tokens in logs, tests, docs, or screenshots.
- [ ] I reviewed new env vars, defaults, and external calls for fail-closed behavior.
- [ ] I verified that sensitive output remains sanitized in API responses, metrics, readiness, logs, and audit paths.

## Docs Checklist

- [ ] I updated README and/or docs for behavior, env vars, APIs, or operator workflows that changed.
- [ ] I called out new limitations or follow-on work honestly.

## Migration Checklist

- [ ] No schema migration is needed.
- [ ] A schema migration is included and reviewed for downgrade/rollback implications.
- [ ] If models changed, I explained why a migration is or is not required.
- [ ] An Alembic smoke test was run if schema-affecting changes were made.

## Notes For Reviewers

- Risk areas:
- Rollout considerations:
- Follow-up work:

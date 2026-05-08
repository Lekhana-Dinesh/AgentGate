# Security Policy

AgentGate is a production-minded control plane for enterprise AI agents. Security issues should be handled carefully and privately.

This root `SECURITY.md` is the public repository policy.
Product controls, hardening details, and current guardrails live in [docs/SECURITY.md](docs/SECURITY.md).

## Security Review Package

- [Security Overview](docs/SECURITY.md)
- [Threat Model](docs/security/THREAT_MODEL.md)
- [Security Review Checklist](docs/security/SECURITY_REVIEW_CHECKLIST.md)
- [Incident Response](docs/security/INCIDENT_RESPONSE.md)
- [Audit Integrity](docs/security/audit-integrity.md)

## Supported Versions

Until the project starts publishing stable tagged releases, only the latest state of the default branch is considered actively supported for security fixes.

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Older commits, forks, or unpublished snapshots | No |

## Private Security Contact

Preferred private contact for security reports:

- `security@example.com` (placeholder only; replace before broader private or public sharing)

If GitHub private vulnerability reporting is enabled for the repository, you may use that path instead.

This repository does not currently claim:

- a paid bug bounty program
- a formal enterprise security support process
- a guaranteed response SLA

For the current private-review phase, the supported disclosure scope is:

- the latest state of `main`
- the private-review package and evaluator workflows shared by the maintainers
- privately shared evaluation or pilot environments operated by the maintainers or a design partner

Out of scope for this lightweight disclosure path:

- feature requests or roadmap asks without a concrete vulnerability
- vulnerabilities that exist only in materially modified forks or unpublished local changes
- issues that depend entirely on third-party systems outside AgentGate's control
- public posting of sensitive details before the maintainers have a chance to review them privately

## Responsible Disclosure

Do not open public GitHub issues for live vulnerabilities.
Do not post secrets, tokens, cookies, `.env` contents, protected payloads, or customer data anywhere in a public issue or pull request.

Preferred disclosure flow:

1. Use GitHub private vulnerability reporting if it is enabled for the repository.
2. Otherwise email `security@example.com` as the current placeholder private contact and replace that address before broader sharing.
3. Include the expected report contents listed below and sanitized evidence only.
4. Do not publish sensitive details in public issues, pull requests, chat threads, or screenshots while the report is under review.

Repository maintainers should replace any placeholder contact process with a real security contact before broad public launch.

## What To Include In A Report

- short summary of the issue
- Affected component or route
- Impact and suspected severity
- Reproduction steps
- Affected commit, branch, image tag, or deployment shape if known
- Required configuration or preconditions
- Sanitized logs or traces
- Proof-of-concept request, payload, or sequence if one exists and can be shared safely
- Suggested mitigation if known

## Private Review Expectations

For private review, please keep the first report practical and minimally sensitive:

- use sanitized examples wherever possible
- say whether the issue affects local-only setup, the self-hosted production-style profile, or both
- say whether the issue is reproducible from the documented private-review package
- avoid sending bulk credential dumps, database exports, or unrelated internal documents

The maintainers may ask follow-up questions or request a reduced reproduction before validating severity.

## What Not To Include Publicly

- Access tokens
- GitHub, Slack, OIDC, or API credentials
- Raw payload encryption keys
- `.env` files
- Decrypted execution payloads
- Customer or tenant data

## Security Hardening Ideas

Use the public issue tracker for non-sensitive hardening work only, such as:

- rate limiting improvements
- CI hardening
- observability gaps
- deployment guardrails
- secret scanning hygiene

Do not use the public issue tracker for:

- live exploit details
- private tenant data
- real secrets or credential material
- unredacted proof-of-concept payloads that would create avoidable risk

## Repository Hygiene

This repository includes CI validation and secret-scanning guardrails, but maintainers and contributors are still responsible for reviewing changes before pushing public commits.

- Keep `.env` and local database files untracked.
- Treat demo credentials as documentation fixtures only, never as deployable defaults.
- Run `python scripts/check-no-live-secrets.py` before public pushes that modify docs, examples, or workflows.
- CI also runs Ruff, Bandit, `npm audit` high+, Trivy high and critical filesystem checks, and an advisory `pip-audit` pass for backend dependencies.
- Automated tooling is there to reduce regressions, not to replace threat modeling, code review, or manual security review.
- Rotate any accidentally exposed secret immediately, even if it appeared only in a draft branch or pull request.

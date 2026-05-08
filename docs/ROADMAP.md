# Roadmap

## Near Term

- Expand governed connector coverage beyond the current GitHub, Jira, and MCP foundations
- Add safer browser-side CRUD for connector and identity configuration that still relies on docs or APIs today
- Add API key lifecycle management views in the UI
- Add richer trace summaries and decision drill-downs
- Improve audit event filtering and export ergonomics
- Improve pagination, cursor-based API responses, and policy authoring UX with structured rule builders

## Security Hardening

- SAML support and broader SCIM coverage such as Groups, richer filters, role sync, and managed token lifecycle
- Broader external secret-manager support and cloud KMS coverage beyond the current env-backed and AWS KMS foundations
- Stronger immutable-evidence options beyond the current external checkpointing foundation
- Richer approval-notification options beyond the current outbound Slack and job-backed foundation
- Proxy-aware client IP trust and richer abuse throttling policy
- Stronger API key rotation and expiry policies

## Platform Scale

- Lease renewal, leader election, and stronger distributed orchestration beyond the current worker and scheduler foundations
- Deeper observability, tracing, and alerting beyond the current starter metrics, dashboards, and alert rules
- Postgres query optimization and indexing reviews
- Deployment patterns beyond the current Compose-based self-hosted profile
- Multi-region deployment patterns

## Decision Intelligence

- Hybrid deterministic plus model-assisted intent analysis
- Policy simulation and dry-run evaluation
- Risk model calibration with historical feedback
- Reviewer feedback loops for policy tuning

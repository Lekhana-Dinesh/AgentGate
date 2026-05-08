# Changelog

This project uses a lightweight changelog and pre-1.0 release discipline.

- Release tags should use `v0.x.y`.
- A `controlled-pilot release` is a curated pre-1.0 checkpoint for private reviewers, design partners, and narrow self-hosted pilot work.
- It is not an enterprise GA signal, a managed SaaS release, or a compliance claim.

## [Unreleased]

### Controlled-Pilot Foundation

- Runtime governance foundation for agent tool calls with tenant-aware auth, deterministic intent and risk evaluation, policies, approvals, audit, traces, and governed execution.
- GitHub-first connector posture with governed Jira foundation as optional second-phase scope and tightly allowlisted HTTP MCP foundation kept off by default unless internal and explicitly reviewed.
- Operator surfaces for onboarding, settings, tools, policies, jobs, audit integrity, audit exports, retention, scheduled tasks, user lifecycle, and agent API key lifecycle management.
- Security foundations including payload protection, optional AWS KMS-backed key handling, cookie-session hardening, audit integrity, external checkpointing, and minimal SCIM Users support alongside OIDC.
- Controlled-pilot operations package including deployment validation, API evaluation collection, pilot policy pack, backup and restore guidance, observability starter assets, and pilot rehearsal runner.
- Private-review and design-partner package including pilot scope, pilot readiness review, outreach and preflight guidance, share-package guidance, and release-candidate review material.

### Current Posture Notes

- AgentGate is positioned as controlled-pilot ready, not enterprise GA.
- First live pilot scope should stay GitHub-first, with Jira as deliberate follow-on scope and MCP disabled by default unless internal and tightly allowlisted.
- Self-hosted production-style Compose is a credible pilot baseline, but it is not a managed platform, HA architecture, Kubernetes package, or compliance certification.

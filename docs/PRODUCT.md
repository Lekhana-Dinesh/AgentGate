# Product

## Positioning

AgentGate is a runtime security and governance platform for enterprise AI agents. It intercepts agent tool calls, checks identity, intent, policy, data sensitivity, and risk, then allows, blocks, routes risky actions for review, or records them for audit and incident response.
The current repo is best positioned as controlled-pilot ready for GitHub-first, self-hosted evaluations, not as enterprise GA, managed SaaS, or a compliance-certified platform.

## Core Buyer Personas

- AI platform team
- developer-platform or engineering productivity owner
- Enterprise architecture team
- Security engineering team
- AI governance team
- CTO or CISO sponsor

## Core Problem

Companies want AI agents to use real business tools, but they cannot safely allow uncontrolled autonomous actions against CRM systems, email, databases, ticketing, and internal APIs.

## Product Pillars

- Runtime authorization for agent actions
- Tenant-aware governance controls
- Deterministic policy enforcement
- Human approval for risky actions
- Full auditability and replayability
- Connector extensibility beyond a single protocol

## Current Scope In This Repo

- Control-plane API and admin dashboard
- Local auth for development plus optional OIDC login, cookie-session hardening, and a minimal SCIM Users foundation
- Agent registry, policies, approvals, audit, traces, jobs, retention, scheduled tasks, and audit-integrity verification
- Mock adapters for realistic demos and tests
- GitHub as the strongest current real connector, with Jira as a constrained optional connector and MCP as a tightly allowlisted HTTP-only foundation
- Self-hosted production-style Compose profile, deployment validator, backup/restore guidance, observability starter assets, API evaluation collection, and a conservative pilot policy pack

## Explicit Non-Claims

This project does not currently claim:

- Enterprise GA or managed SaaS operations
- Guaranteed safety
- Full prevention of all prompt injection or indirect tool abuse
- SOC 2 certification
- Complete enterprise deployment maturity
- SAML support
- Full SCIM identity governance
- Full secret-manager coverage or non-AWS cloud KMS parity
- Built-in immutable evidence storage without destination-side WORM or Object Lock controls

It does provide a strong technical foundation for controlled pilot deployments, runtime policy enforcement, and operator review workflows.

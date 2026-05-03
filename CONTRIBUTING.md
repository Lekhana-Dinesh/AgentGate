# Contributing

## Principles

- Keep the runtime decision core deterministic first.
- Preserve tenant isolation in every query and API path.
- Prefer explicit policies and typed contracts over hidden behavior.
- Add tests for new policy, intent, or risk logic before expanding heuristics.
- Document limitations honestly when a feature is only partially implemented.

## Local Workflow

1. Install backend and frontend dependencies.
2. Run the seed script to load demo data.
3. Start API and web locally.
4. Add or update tests for the behavior you changed.
5. Run the relevant checks before opening a PR.

## Backend Conventions

- Keep routers thin and push business logic into services.
- Use Pydantic models for request and response contracts.
- Treat policy, risk, and intent modules as high-value, heavily tested code.
- Fail closed when uncertainty affects high-risk actions.

## Frontend Conventions

- Use the typed API client in `apps/web/lib/api.ts`.
- Keep dashboard UI clear, operational, and enterprise-focused.
- Handle loading, error, and empty states on every data-driven page.

## Suggested Checks

```bash
cd apps/api
python -m pytest app/tests -q
python -m compileall app

cd ../web
npm run build
```

## Pull Request Expectations

- Explain user-visible behavior changes.
- Call out any security implications.
- Mention new environment variables or migrations.
- Include screenshots for dashboard changes when practical.


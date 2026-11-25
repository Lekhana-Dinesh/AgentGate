# Local development and synthetic demo

Use the [README quickstart](../../README.md#quickstart) to run the full development stack. The Compose project owns a separate network and PostgreSQL volume. Use a unique project name to keep multiple demonstrations independent. The published ports bind to loopback.

When PostgreSQL or Redis host ports are occupied, set `AGENTGATE_LOCAL_POSTGRES_PORT=55432` and `AGENTGATE_LOCAL_REDIS_PORT=56379` in your shell before starting Compose. Container-to-container connection strings stay the same. If you change the web or API port, also align `AGENTGATE_PUBLIC_APP_URL`, `AGENTGATE_PUBLIC_API_URL`, `AGENTGATE_CORS_ORIGINS`, and `NEXT_PUBLIC_API_BASE_URL`. Rebuild the frontend after changing its API URL.

For troubleshooting, use the same project name as in the quickstart.

```sh
docker compose --env-file .env.example -p agentgate-demo ps -a
docker compose --env-file .env.example -p agentgate-demo logs --tail=40 migrate api worker scheduler web
docker compose --env-file .env.example -p agentgate-demo exec -T api python -m alembic current
docker compose --env-file .env.example -p agentgate-demo exec -T postgres pg_isready -U agentgate -d agentgate
docker compose --env-file .env.example -p agentgate-demo exec -T redis redis-cli ping
```

The API `/ready` response checks the database and Redis broker. Check worker activity in the console or `GET /v1/workers/status`. The scheduler runs as a separate process. To check a scheduled run, create an `audit_integrity_verify` task with `POST /v1/scheduled-tasks`, use an interval of 60 seconds or more, and wait for the next run. Confirm that **Scheduled Tasks** advances its next-run timestamp and **Jobs** shows the resulting verification job.

## Run on your host with SQLite

Use Python 3.12 and Node.js 22. Activate a Python virtual environment before installing dependencies. In the first terminal, start from the repository root.

```sh
cd apps/api
python -m pip install -e ".[dev]"
```

Set the environment for this terminal before migration and startup.

| Bash or Zsh | PowerShell |
| --- | --- |
| `export AGENTGATE_ENV=development` | `$env:AGENTGATE_ENV = 'development'` |
| `export AGENTGATE_DATABASE_URL=sqlite:///./agentgate_local_demo.db` | `$env:AGENTGATE_DATABASE_URL = 'sqlite:///./agentgate_local_demo.db'` |
| `export AGENTGATE_JOB_DISPATCH_MODE=inline` | `$env:AGENTGATE_JOB_DISPATCH_MODE = 'inline'` |
| `export AGENTGATE_JOB_BROKER=database` | `$env:AGENTGATE_JOB_BROKER = 'database'` |

```sh
python -m alembic upgrade head
python -m app.db.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal at the repository root:

```sh
cd apps/web
npm ci
npm run dev
```

Open `http://localhost:3000` and use the [synthetic accounts and walkthrough](../../README.md#demo-walkthrough). The SQLite profile exercises the same UI and policy paths with inline job processing. Use Compose to exercise the Redis-backed worker and scheduler.

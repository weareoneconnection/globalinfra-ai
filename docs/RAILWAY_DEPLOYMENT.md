# Railway deployment

GlobalInfra AI is an isolated monorepo. It must be deployed as separate
Railway services; Railpack cannot infer an application from the repository
root.

## Services

| Railway service | Source | Root directory | Health check |
| --- | --- | --- | --- |
| `web` | `weareoneconnection/globalinfra-ai` | `/apps/web` | `/` |
| `api` | `weareoneconnection/globalinfra-ai` | `/services/api` | `/health` |
| `Postgres` | Railway managed PostgreSQL | n/a | managed |

Redis is not required by the current runtime. The URL remains in the settings
contract for the future asynchronous worker tier.

Railway detects the `Dockerfile` inside each root directory. Both images listen
on Railway's injected `PORT` and retain their Docker Compose defaults.

## Variables

Set these on `api`:

```dotenv
PORT=8000
DATABASE_URL=${{Postgres.DATABASE_URL}}
LLM_MODE=mock
REQUIRE_API_KEY=false
CORS_ORIGINS=https://<web-domain>
```

To use OpenAI, additionally set `LLM_MODE=openai`,
`OPENAI_COMPAT_API_KEY` as a sealed Railway variable, and the desired
`OPENAI_COMPAT_MODEL`. Never commit the key.

Set these on `web`:

```dotenv
PORT=3000
API_INTERNAL_URL=http://api.railway.internal:8000
```

If the API key gate is enabled, set the same secret as `API_KEY` on `api` and
`API_SERVICE_KEY` on `web`.

## Deployment order

1. Provision `Postgres`.
2. Deploy `api` and run `alembic upgrade head` as its pre-deploy command.
3. Deploy `web`.
4. Generate a public domain for `web`. The API can remain private because the
   Next.js `/backend/*` proxy calls it over Railway private networking.

Do not deploy `docker-compose.yml` as one Railway service. Railway maps Compose
services to separate platform services and does not run the Compose file as the
application entry point.

# Database migrations (Alembic)

Introduced in V1.3 M1. These migrations are the managed-deployment path for the
API's relational schema. The offline/test path is unchanged — `app.main`'s
lifespan still runs `Base.metadata.create_all` + `seed()`, so local dev, CI and
the eval harness do not need Alembic.

## Layout

- `alembic.ini` (in `services/api/`) — minimal config. The database URL is **not**
  stored here; `env.py` reads it from app settings (`DATABASE_URL` / `.env`).
- `env.py` — binds Alembic to `app.database.Base.metadata` (with all models
  imported) and to the app's own `settings.database_url`.
- `versions/0001_baseline_schema.py` — the pre-existing V1.2 tables, captured as
  the migration baseline.
- `versions/0002_intake_tables.py` — adds `intake_submissions` and
  `source_documents` (V1.3 M1 Universal Intake).

## Running

Always run from `services/api/` (the same working directory uvicorn/Docker use):

```bash
cd services/api

# Bare / fresh database → create everything:
DATABASE_URL=postgresql+psycopg://user:pass@host/db alembic upgrade head

# Database already created by the historic create_all path → adopt the
# baseline without re-running it, then apply only the new migrations:
DATABASE_URL=postgresql+psycopg://user:pass@host/db alembic stamp 0001
DATABASE_URL=postgresql+psycopg://user:pass@host/db alembic upgrade head

# Inspect / roll back:
alembic current
alembic downgrade -1
```

## Consistency guarantee

The Alembic schema and the `create_all` schema are kept identical (CI asserts a
bare `alembic upgrade head` succeeds; a schema diff check is in the test notes).
When you add a model to `app/models.py`, add a matching migration here so both
paths stay in sync.

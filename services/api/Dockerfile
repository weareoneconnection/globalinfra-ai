FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Phase 9.1 reproducible evaluation cases are loaded by the public evidence
# endpoint at runtime, so the versioned JSONL suite ships with the API image.
COPY evals ./evals
# Alembic config + migrations ship in the image so a deployment can run
# `alembic upgrade head` against a managed database (Postgres). The default
# CMD still boots via create_all for the zero-config demo/offline path.
COPY alembic.ini ./
COPY migrations ./migrations
EXPOSE 8000
# Railway injects PORT; Docker Compose keeps the documented 8000 default.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

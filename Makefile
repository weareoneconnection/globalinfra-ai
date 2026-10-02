.PHONY: up down logs api web eval test

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

api:
	cd services/api && uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && API_INTERNAL_URL=http://localhost:8000 npm run dev

eval:
	cd evals && python3 run_eval.py

# Requires services/api/requirements-dev.txt installed (pytest + the runtime
# deps in requirements.txt). Uses its own SQLite DB; see services/api/tests/conftest.py.
test:
	cd services/api && python3 -m pytest tests -q

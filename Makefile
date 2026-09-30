.PHONY: up down logs api web eval

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

.PHONY: setup db api worker web test eval eval-llm seed up

setup:            ## install deps, create DBs, migrate
	cd backend && uv sync
	cd frontend && npm install
	-createdb jobpilot; -createdb jobpilot_test
	cd backend && uv run alembic upgrade head

api:              ## FastAPI on :8000 (hosts the worker + scheduler unless EMBEDDED_WORKER=false)
	cd backend && uv run uvicorn app.main:app --reload --port 8000

worker:           ## standalone queue worker (scale horizontally)
	cd backend && uv run python -m app.worker

web:              ## Next.js on :3000
	cd frontend && npm run dev

test:
	cd backend && uv run pytest -q
	cd frontend && npm run typecheck

eval:             ## offline evals: match quality + no-fabrication guard
	cd backend && uv run python -m evals.run_evals

eval-llm:         ## adds Claude fit reviews + live Tailor fabrication rate (uses API credits)
	cd backend && uv run python -m evals.run_evals --llm

seed:             ## demo account with the sample resume
	cd backend && uv run python -m scripts.seed_demo

up:               ## everything in Docker
	docker compose up --build

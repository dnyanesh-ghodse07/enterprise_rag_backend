# ═══════════════════════════════════════════════════════════════
# Cognix — Developer Commands
# ═══════════════════════════════════════════════════════════════
#
# Usage:
#   make help          Show all available commands
#   make dev           Start everything for development
#   make down          Stop all services
#   make test          Run tests
#   make lint          Run linter
#
# ═══════════════════════════════════════════════════════════════

.PHONY: help dev down test lint format db-up db-down backend logs clean

# Default target — shows help
help: ## Show this help message
	@echo "╔══════════════════════════════════════════════════╗"
	@echo "║          Cognix — Developer Commands             ║"
	@echo "╚══════════════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─── Development ───────────────────────────────────────────
dev: db-up backend ## Start all services and backend server

db-up: ## Start infrastructure services (PostgreSQL, Redis, Qdrant, Neo4j)
	docker compose up -d
	@echo "⏳ Waiting for services to be healthy..."
	@sleep 5
	@echo "✅ Infrastructure services are running"

db-down: ## Stop infrastructure services
	docker compose down

down: ## Stop everything (infrastructure + app)
	docker compose down

backend: ## Start the FastAPI backend server
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ─── Testing ───────────────────────────────────────────────
test: ## Run tests
	uv run pytest -v

test-cov: ## Run tests with coverage report
	uv run pytest --cov=app --cov-report=html

# ─── Code Quality ─────────────────────────────────────────
lint: ## Run linter
	uv run ruff check .

format: ## Format code
	uv run ruff format .

type-check: ## Run type checker
	uv run mypy app/

# ─── Database ─────────────────────────────────────────────
db-migrate: ## Run database migrations
	uv run alembic upgrade head

db-rollback: ## Rollback last migration
	uv run alembic downgrade -1

db-revision: ## Create a new migration (usage: make db-revision MSG="add users table")
	uv run alembic revision --autogenerate -m "$(MSG)"

# ─── Logs ─────────────────────────────────────────────────
logs: ## View all service logs
	docker compose logs -f

logs-backend: ## View backend logs only
	docker compose logs -f backend

# ─── Cleanup ──────────────────────────────────────────────
clean: ## Remove all containers and volumes (DESTRUCTIVE!)
	docker compose down -v
	@echo "🧹 All containers and volumes removed"

reset: clean db-up ## Full reset — destroy everything and start fresh
	@echo "🔄 Environment has been reset"
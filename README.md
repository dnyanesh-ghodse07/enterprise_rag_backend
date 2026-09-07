# Cognix Backend

Cognix backend is the API layer for the Cognix AI platform. It provides authentication, multi-tenant user management, health checks, and a foundation for document, vector, and agent workflows.

## Tech Stack

- Python 3.14+
- FastAPI
- SQLAlchemy 2
- PostgreSQL
- Redis
- Alembic migrations
- JWT-based authentication
- Docker Compose for local infrastructure

## Project Structure

```text
backend/
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   ├── router.py
│   │   └── v1/
│   │       ├── auth.py
│   │       └── health.py
│   ├── config.py
│   ├── core/
│   │   ├── database.py
│   │   ├── exceptions.py
│   │   └── security.py
│   ├── main.py
│   ├── models/
│   │   ├── base.py
│   │   ├── refresh_token.py
│   │   ├── tenant.py
│   │   └── user.py
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── common.py
│   │   ├── health.py
│   │   └── user.py
│   └── services/
│       └── auth_service.py
├── alembic/
├── tests/
├── docker-compose.yml
├── makefile
├── pyproject.toml
├── alembic.ini
└── README.md
```

## Features

- FastAPI app factory with CORS and centralized error handling
- JWT auth flows with login, refresh, logout, and profile access
- Tenant-aware data model foundation
- SQLAlchemy async database access
- Health and readiness checks for dependency monitoring
- Local infra setup using PostgreSQL, Redis, Qdrant, and Neo4j via Docker
- Alembic for database migrations

## Prerequisites

Before running the backend locally, make sure you have:

- Python 3.14+
- uv (recommended package manager)
- Docker and Docker Compose
- Git

## Local Setup

1. Open a terminal in the backend directory:

```bash
cd backend
```

2. Install dependencies:

```bash
uv sync
```

3. Start required infrastructure services:

```bash
docker compose up -d
```

4. Start the FastAPI server:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. Open the API docs in your browser:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Environment Configuration

The app loads settings from environment variables and the `.env` file when present. The default configuration is defined in `app/config.py`.

Common values include:

- `APP_NAME`
- `APP_VERSION`
- `DEBUG`
- `ENVIRONMENT`
- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `OPENAI_API_KEY`

Example `.env`:

```env
APP_NAME=Cognix
ENVIRONMENT=development
DEBUG=true
DATABASE_URL=postgresql+asyncpg://cognix:cognix_dev@localhost:5434/cognix
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=change-me-in-production
OPENAI_API_KEY=sk-your-key-here
```

## Useful Commands

This project includes a `makefile` with common tasks:

```bash
make help
make dev
make db-up
make db-down
make test
make lint
make format
make db-migrate
make db-rollback
make clean
```

### Core commands

```bash
# Start infrastructure and backend
make dev

# Run tests
make test

# Run lint
make lint

# Format code
make format

# Apply migrations
make db-migrate
```

## API Overview

The main API router is mounted under `/api/v1`.

### Auth endpoints

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

### Health endpoints

- `GET /health`
- `GET /health/ready`

## Database and Migrations

This project uses Alembic for schema management.

To create a new migration:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

To apply migrations:

```bash
uv run alembic upgrade head
```

To revert the last migration:

```bash
uv run alembic downgrade -1
```

## Testing

Run the backend test suite with:

```bash
uv run pytest -v
```

If you want coverage:

```bash
uv run pytest --cov=app --cov-report=html
```

## Docker Infrastructure

The `docker-compose.yml` file starts local development services:

- PostgreSQL on `localhost:5434`
- Redis on `localhost:6379`
- Qdrant on `localhost:6333`
- Neo4j on `localhost:7474` and `localhost:7687`

Use:

```bash
docker compose up -d
docker compose logs -f
docker compose down
```

## Notes

- The app is designed for local development first, with production-ready patterns such as environment-based configuration and centralized exception handling.
- Do not leave `DEBUG=true` or weak default secrets in production.
- Keep `.env` values secure and rotate credentials for any deployed environment.

## License

This project is currently intended for internal development and project use unless a separate license is added.

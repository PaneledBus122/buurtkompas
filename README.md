# buurtkompas

Netherlands neighborhood-comparison dashboard, built on public CBS/PDOK open data.

This is a personal data-engineering portfolio project (in active development), demonstrating a full pipeline from raw open data to a queryable, mapped dashboard — with a natural-language query layer as the eventual differentiator from existing tools (Check je wijk, Buurtvergelijker.nl).

**Status**: Phase 0 — local dev environment and CI scaffolding. No application functionality yet.

## Tech stack

| Layer | Tool |
|---|---|
| Dependency management | [uv](https://github.com/astral-sh/uv) |
| Database | PostgreSQL 16 + PostGIS 3.4 (via Docker) |
| Transform | dbt (planned) |
| Orchestration | Apache Airflow (planned) |
| Frontend | TBD (planned) |
| Deployment | Azure (planned) |

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (manages Python itself — no separate Python install needed)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

## Setup

```bash
git clone https://github.com/PaneledBus122/buurtkompas.git
cd buurtkompas

# Install dependencies and create the virtual environment
uv sync

# Set up git pre-commit hooks (ruff lint + format)
uv run pre-commit install

# Start local PostgreSQL + PostGIS
docker compose up -d
```

## Project structure
src/buurtkompas/
├── extract/ # Data extraction from CBS/PDOK sources
├── load/ # Loading into PostgreSQL
└── dashboard/ # Frontend (TBD)
dbt/ # Transform layer (staging/marts)
dags/ # Airflow DAGs
tests/


## License

MIT — see [LICENSE](LICENSE).
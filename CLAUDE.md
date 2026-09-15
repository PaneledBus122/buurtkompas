# buurtkompas — Claude Code Context

## Project
Neighborhood-comparison dashboard for Eindhoven, NL (CBS + PDOK data). Dual
purpose: a software/data-engineering portfolio piece, and a real decision
tool for the maintainer's own relocation to Eindhoven.

## Tech stack
- Extract: Python (pandas/requests) — CBS StatLine OData, PDOK WFS
- Load: Postgres+PostGIS (Neon in prod), SQLAlchemy Core + GeoAlchemy2
- Transform: dbt (long-format marts, gemeente-partitioned percentile
  ranking, coverage-threshold handling for missing data, re-ranked
  weighted score)
- Frontend: Streamlit + pydeck + CARTO free basemap
- Deploy: Docker + GitHub Actions -> Google Cloud Run, Workload Identity
  Federation (no long-lived credentials), Secret Manager for DATABASE_URL
- Dependency manager: uv. Lint/format: ruff only.

## Conventions
- Everything in this repo (code, comments, README, docs/, commit
  messages, PR titles/descriptions) is English-only.
- Branch -> PR -> CI (ruff + pytest) -> merge to `main`. Solo-dev repo:
  branch protection requires passing checks but NOT approvals.
- Category tagging for indicators happens at extract time
  (`extract/cbs.py`'s `MEASURES` dict) — never re-tag downstream.
- Long-format schema (`dim_region`/`dim_indicator`/`fact_indicator`) by
  design, so new indicators/categories don't require migrations.

## Status (2026-09-15)
Phases 0–6 complete and merged. Live at:
https://buurtkompas-dashboard-420148358953.europe-west4.run.app
(Cloud Run europe-west4, Neon eu-central-1).

## Known gotchas from real deploy troubleshooting
- `gcloud iam workload-identity-pools providers create-oidc` requires
  `--attribute-condition` now (recent gcloud policy change).
- `.dockerignore`'s `*.md` also excludes README.md, which hatchling
  needs for `pyproject.toml`'s `readme` field — keep a `!README.md`
  exception AND an explicit `COPY README.md ./` in the Dockerfile. These
  are two separate mechanisms; fixing one without the other still fails.
- `deploy-cloudrun.yml`'s push `paths` filter won't retrigger for a
  commit that only touches files outside that list — use
  `workflow_dispatch` to force a run when needed.
- dbt against Neon needs `sslmode` as a discrete `profiles.yml` key, not
  a `?sslmode=` URL suffix (that only works for `DATABASE_URL`-style
  SQLAlchemy/psycopg2 connections).

## Next priority (decided 2026-09-15): data realism upgrade
1. Safety/crime indicator (`category='safety'`) — source:
   politieopendata.cbs.nl. No schema migration needed.
2. Commute time to a user-specified address — needs a routing API
   (leaning OpenRouteService for its free tier) and a shift from static
   batch indicators to a request-time lookup.
3. Real transaction housing prices to augment/replace WOZ assessed
   value — use CBS actual sale-price statistics; do not scrape listing
   sites (Funda/Pararius ToS risk).

## Where the fuller planning history lives
Korean-language plan + decision log live in a claude.ai Project
("Scientific Developer Showcase" → `eindhoven-dashboard-plan.md`,
`buurtkompas-progress-log.md`), not in this repo. Ask the user to paste
a section if historical rationale is needed.

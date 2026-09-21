# CLAUDE.md

## What this project is
Buurtkompas: a data-engineering portfolio project comparing Eindhoven and
Veldhoven (NL) neighbourhoods (buurten) using CBS/PDOK open data. Scope is
`GEMEENTE_CODES` in `extract/cbs.py` (single source of truth; pdok.py and
politie.py import it). Pipeline: batch ETL -> dbt
(staging -> intermediate -> marts) -> Postgres/PostGIS (Neon, serverless with
auto-suspend) -> Streamlit + pydeck dashboard -> Google Cloud Run (GitHub
Actions CI/CD, Workload Identity Federation, Secret Manager for
DATABASE_URL/ORS_API_KEY).

Live dashboard: https://buurtkompas-dashboard-420148358953.europe-west4.run.app

## Repo layout
```
src/buurtkompas/
  extract/    cbs.py, politie.py, pdok.py -- CBS/PDOK pulls, write data/raw/*.csv|.geojson
  load/       loader.py (batch ETL), schema.py (SQLAlchemy Core tables)
  dashboard/  app.py (entrypoint), data.py, colors.py, commute.py, footer.py, static_pages.py,
              profile_form.py (5-input form -> starting category-weight sliders)
  weighting/  engine.py -- pure, UI-free category-weighting engine (UserProfile ->
              weights summing to 100, iterative floor-clip); used by profile_form.py
  nlu/        classifier.py -- free text -> the five UserProfile axes via a local
              sentence-embedding model. NOT wired into the dashboard yet
dbt/
  models/staging/       stg_dim_region.sql, stg_dim_indicator.sql, stg_fact_indicator.sql
  models/intermediate/  int_indicator_percentile.sql
  models/marts/         fct_category_score.sql   <- what the dashboard reads
  seeds/indicator_direction.csv
  profiles.yml, dbt_project.yml
tests/        test_cbs.py, test_politie.py, test_commute.py,
              test_dashboard_data.py, test_dashboard_colors.py, test_weighting.py,
              test_profile_form.py, test_nlu_classifier.py (loads the real model)
.streamlit/config.toml   theme (accent color, fonts, dark palette) -- must ship in Docker image
.github/workflows/       lint.yml (pytest+ruff on PR/push), deploy-cloudrun.yml (paths-filtered)
docs/         cbs-api-notes.md, deployment.md (Cloud Run + Neon one-time setup)
```
No `dbt/tests/` or `dbt/macros/` directories exist — all dbt tests are schema
tests (not_null/unique/relationships/accepted_values) declared in the
`_*.yml` files next to each model, run via `dbt build`/`dbt test`.

## Key files
- `src/buurtkompas/dashboard/app.py` — Streamlit entrypoint. `main()` builds
  an explicit `st.Page` list (not the `pages/`-directory convention) and
  calls `st.navigation(..., position="hidden")`; `render_dashboard_page()`
  is the actual Home/dashboard content. `get_engine()` is `@st.cache_resource`
  with `pool_pre_ping=True, pool_recycle=280` — required because Neon
  auto-suspends after ~5min idle; removing these reintroduces intermittent
  `SSL connection has been closed unexpectedly` errors. `CATEGORY_LABELS`
  maps category slug -> display label; the education category's real slug is
  `"schools"`, not `"education"` — a past bug had this backwards.
- `src/buurtkompas/dashboard/profile_form.py` — the structured profile form
  rendered above the map. On submit it computes starting weights once via
  `weighting.engine.compute_weights`, converts them to the sliders' 0-10 scale,
  and stores them under `st.session_state["pending_slider_weights"]`;
  `render_weight_sliders()` in `app.py` consumes that key before the slider
  widgets exist. After that one-time apply the sliders are independent again,
  and a fresh page load starts from equal weights. Its 0-10 slider constants
  intentionally duplicate `app.py`'s (importing back would be circular).
- `src/buurtkompas/nlu/classifier.py` — `classify(text)` maps free text to the
  five `UserProfile` axes (`ClassificationResult.to_profile()` leaves any axis it
  can't place at the default; it never computes weights, `compute_weights()`
  still does). Few-shot nearest-example matching with
  `sentence-transformers/all-MiniLM-L6-v2` on CPU: reference phrases per level,
  cosine similarity, one threshold (`_DEFAULT_THRESHOLD`), and each clause of
  the input is matched separately. **Not wired into the dashboard yet** (no
  text box, no `app.py` or `profile_form.py` changes). The reference phrases and
  threshold are tuned against the labeled sets in `tests/test_nlu_classifier.py`
  (per-axis accuracy, pooled recall / false-positive bars): re-run it after any
  phrase or model change, and keep test sentences out of the phrases.
- `src/buurtkompas/dashboard/data.py` — DB access + pure scoring transforms:
  `fetch_category_scores()`, `compute_overall_score()` (per-region weight
  renormalization over available categories, 3-of-6 coverage gate, then
  `pandas.Series.rank(pct=True)` re-rank), `scale_bar_widths()` (ranked-table
  bar scaling).
- `src/buurtkompas/dashboard/colors.py` — `_COLOR_STOPS`: diverging
  blue->gray->orange scale, colorblind-safe by design (do not revert to
  red/yellow/green). `legend_gradient_css()` derives the map legend's CSS
  gradient from the same stops the map itself uses.
- `src/buurtkompas/dashboard/footer.py` / `static_pages.py` — the 4
  informational pages (Methodology/About/Privacy/Contact), reachable only via
  the footer's `st.page_link`s, never the sidebar.
- `src/buurtkompas/load/loader.py` — one-shot batch ETL (`main()`); its own
  `create_engine()` call needs no `pool_pre_ping` (the process exits after
  running, so it never sits idle in a pool across a Neon suspend).
- `dbt/models/marts/fct_category_score.sql` — the mart the dashboard actually
  queries; coverage-gated, re-ranked percentile per (region, category, year).
- `.streamlit/config.toml` — native theming. Must be `COPY`'d into the Docker
  image explicitly (Dockerfile already does this — check it's still there if
  you touch the Dockerfile).

## Build, test, run
```bash
uv sync                                    # install deps
uv run pre-commit install                  # one-time: git hooks (ruff lint+format)
uv run pytest                              # full test suite
uv run ruff check . && uv run ruff format --check .

docker compose up -d                       # local Postgres/PostGIS (buurtkompas-db, :5432)
uv run python -m buurtkompas.extract.cbs
uv run python -m buurtkompas.extract.politie
uv run python src/buurtkompas/extract/pdok.py     # rarely needed -- buurt geometries barely change
uv run python -m buurtkompas.load.loader          # reads data/raw/*, writes dim_*/fact_indicator
DBT_PROFILES_DIR=dbt uv run dbt build --project-dir dbt   # staging -> intermediate -> marts + tests

uv run streamlit run src/buurtkompas/dashboard/app.py     # local dashboard, http://localhost:8501
```
Against Neon instead of local Postgres: set `DATABASE_URL` (loader/dashboard)
and `DBT_PG_HOST/PORT/USER/PASSWORD/DBNAME` + `DBT_PG_SSLMODE=require` (dbt) —
see `docs/deployment.md`. Use Neon's **direct** (non-pooled) connection for
DDL/loader/dbt; the **pooled** one (in Secret Manager as `DATABASE_URL`) is
only for the deployed app's own runtime reads.

## Conventions
- All code, comments, README, docs/, commit messages, and PR titles/
  descriptions: English only, no exceptions.
- Commits are split by unit of work (feature / bugfix / refactor); messages
  explain *why*, not just what.
- Branch-per-change, PR into `main`. `deploy-cloudrun.yml` auto-deploys on
  merge only when its `paths` filter matches (anything under
  `src/buurtkompas/`, `pyproject.toml`, `uv.lock`, `Dockerfile`, or the
  workflow file itself) — a dbt-only change does NOT trigger a redeploy on its
  own.
- When checking a fresh merge against GitHub, use
  `raw.githubusercontent.com/<owner>/<repo>/refs/heads/main/<path>` rather
  than the `/main/` shorthand — the latter can serve a briefly stale
  CDN-cached copy right after a merge.

## Known gotchas
- **README.md is stale.** It says "Phase 0 — no application functionality
  yet" and "Deployment: Azure (planned)". Both are wrong: the app is a
  working pipeline live on Cloud Run today. Don't trust README's Status/Tech
  stack tables — this file is the source of truth on project state.
- **Raw filenames are stale**: `data/raw/*_eindhoven.*` now hold both
  Eindhoven and Veldhoven rows (renaming needs matching constants in
  `load/loader.py`). Category/overall scores are percentile-ranked *within*
  each gemeente, but the live commute-time score (`commute.py`) is ranked
  across all loaded buurten together, and the ranked table sorts both
  gemeenten into one list.
- **Deploy path filter is deliberately broad**: `deploy-cloudrun.yml` watches
  all of `src/buurtkompas/**` because the Dockerfile copies the whole `src/`
  tree and the dashboard imports sibling packages (`weighting/` today, more
  later). The trade-off is an occasional redeploy for a change the dashboard
  doesn't use (e.g. `extract/`, `load/`); harmless, and safer than a stale
  image.
- **NLU dependencies are heavy** (`sentence-transformers` + PyTorch). `torch` is
  pinned to PyTorch's CPU-only wheel index in `pyproject.toml` (the default
  Linux wheel pulls in GBs of CUDA libraries); `uv.lock` has no nvidia/triton
  packages. Even so, the Dockerfile syncs every project dependency, so the
  deployed image already carries torch although the dashboard doesn't import
  `nlu/` yet. Before wiring it in: pre-download the model into the image at
  build time (otherwise the first request downloads ~90MB from Hugging Face and
  needs egress), and expect a slower cold start. CI (`lint.yml`) also installs
  torch and downloads the model on every run; caching `~/.cache/huggingface`
  would speed it up. Tests need network on a cold cache.
- **Neon auto-suspend**: compute suspends after ~5min idle. Any long-lived
  `create_engine()` used by a process that stays warm (i.e. anything but a
  one-shot script) needs `pool_pre_ping=True` plus a `pool_recycle` below
  ~300s, or it will eventually throw a stale-connection error.
- **`st.html()` with a style-only body silently drops the `<style>` tag** in
  the Streamlit version this project pins (routed to an internal "event
  container" meant to avoid taking up layout space, which in practice never
  lands the tag in the DOM). Use `st.markdown(css, unsafe_allow_html=True)`
  for any global CSS injection instead.
- **Streamlit session_state**: you cannot set `st.session_state[key]` for a
  widget's own key after that widget has already been instantiated in the
  same script run — raises `StreamlitWidgetAlreadyInstantiatedError`, even
  immediately before `st.rerun()`. The pattern used here for "reset" buttons:
  set a `*_pending` flag, call `st.rerun()`, consume the flag (mutate state)
  before the widget is created on the next run. The profile form uses the
  same handoff key (`pending_slider_weights`) but needs no `st.rerun()`: it
  renders above the sliders in the same run, so they consume the key later in
  that run. Keep `render_profile_form()` before `render_weight_sliders()`.
- **CBS has two live API generations** in this codebase: `cbs.py` uses OData
  v4 (table `85984NED`, `@odata.nextLink`, JSON by default) and `politie.py`
  uses OData v3 (table `47018NED` on `dataderden.cbs.nl`, unprefixed
  `odata.nextLink`, needs `$format=json` explicitly or you get XML back).
  Don't assume one extractor's quirks apply to the other.
- `src/buurtkompas/extract/pdok.py` is a one-off script (no `if __name__`
  guard, prints in Korean) that fetches buurt geometries — those change
  rarely, so it's not part of the regular extract-then-load cycle the way
  cbs.py/politie.py are.
- Production secrets (`DATABASE_URL`, `ORS_API_KEY`) live in GCP Secret
  Manager, injected into Cloud Run via `deploy-cloudrun.yml`'s `secrets:`
  block — never as plaintext env vars or GitHub Secrets. Adding a new one
  means updating both the workflow and granting the Cloud Run runtime
  service account `secretmanager.secretAccessor` on it.

## Keeping this file current
Treat a stale CLAUDE.md as a bug. When a PR changes architecture, adds/moves
a key file, or changes a build/run/deploy command, update this file in the
same PR.

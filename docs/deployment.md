# Deployment (Phase 6): Cloud Run + Neon

The dashboard runs as a container on **Google Cloud Run** (free tier, see
below) and reads from a **Neon** Postgres+PostGIS database (also free tier).
Deploys happen automatically via GitHub Actions on every push to `main` that
touches the dashboard, using Workload Identity Federation (no service-account
key ever leaves GCP).

This doc is the one-time setup. Once it's done, shipping a dashboard change
is just: push to `main`.

## Why this stack

- **Cloud Run**: a genuinely perpetual free monthly grant (180,000 vCPU-seconds,
  360,000 GiB-seconds of memory, 2,000,000 requests), not a 12-month trial
  credit. A low-traffic portfolio dashboard stays inside this indefinitely.
- **Neon**: Postgres with PostGIS support, also a perpetual free tier (0.5 GB
  storage, 100 compute-hours/month, autosuspends after 5 minutes idle —
  the trade-off for "free forever" is a few seconds of cold-start latency on
  the first request after a quiet period).
- Both were chosen over Azure's equivalents (Container Apps + Azure Database
  for PostgreSQL) specifically because Azure's managed Postgres free tier is
  a 12-month new-account credit, not a permanent allowance — it would start
  billing on its own a year in. See the decision log in
  `eindhoven-dashboard-plan.md` for the full comparison (Azure OpenAI vs.
  Gemini API free tier was part of that call too, relevant if/when Phase 7's
  natural-language layer gets built).

## 1. Create the Neon database

1. Sign up at [neon.tech](https://neon.tech) (free), create a project (pick
   a region close to Eindhoven, e.g. Frankfurt/`eu-central-1`).
2. In the Neon SQL editor, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```
3. Copy the project's connection string from the Neon dashboard. It looks
   like:
   ```
   postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
   ```

## 2. Run Extract → Load → dbt against Neon (one-time, or whenever data refreshes)

From your own machine, point the existing pipeline at Neon instead of the
local `db` container:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://<user>:<password>@<host>/<dbname>?sslmode=require"
uv run python -m buurtkompas.extract.cbs
uv run python -m buurtkompas.extract.pdok
uv run python -m buurtkompas.load.loader

$env:DBT_PG_HOST = "<host>"
$env:DBT_PG_USER = "<user>"
$env:DBT_PG_PASSWORD = "<password>"
$env:DBT_PG_DBNAME = "<dbname>"
uv run dbt build --project-dir dbt
```

`dbt/profiles.yml` already reads `DBT_PG_HOST`/`DBT_PG_USER`/etc. via
`env_var()` with local-dev defaults (see Phase 3), so the env vars above are
enough on their own for `dbt build` -- with one addition: **Neon requires
TLS**, and dbt's postgres adapter takes that as its own `sslmode` connection
key, not as a `?sslmode=require` suffix on a URL (that suffix only works for
`DATABASE_URL`, which `psycopg2`/SQLAlchemy parse as a URL — dbt's profile
doesn't). Add one line to `dbt/profiles.yml`'s `outputs.dev` block, right
after `dbname`:

```diff
       dbname: "{{ env_var('DBT_PG_DBNAME', 'buurtkompas') }}"
+      sslmode: "{{ env_var('DBT_PG_SSLMODE', 'prefer') }}"
       schema: analytics
```

Defaulting to `prefer` keeps local Docker Compose runs unchanged (no SSL
there, so `prefer` just skips it); set `DBT_PG_SSLMODE=require` alongside
the other `DBT_PG_*` env vars when running against Neon.

## 3. One-time GCP setup

```bash
PROJECT_ID="<your-gcp-project-id>"
REGION="europe-west4"   # Netherlands
REPO="<your-org>/buurtkompas"   # GitHub owner/repo, for the WIF trust condition

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  iamcredentials.googleapis.com secretmanager.googleapis.com

# Artifact Registry: where built images are pushed
gcloud artifacts repositories create buurtkompas \
  --repository-format=docker --location="$REGION"

# Secret Manager: the Neon connection string Cloud Run reads at runtime
printf '%s' "postgresql+psycopg2://<user>:<password>@<host>/<dbname>?sslmode=require" | \
  gcloud secrets create buurtkompas-database-url --data-file=-

# Deploy service account: what GitHub Actions impersonates to build/deploy
gcloud iam service-accounts create buurtkompas-deployer \
  --display-name="buurtkompas GitHub Actions deployer"
DEPLOY_SA="buurtkompas-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOY_SA}" --role="$role"
done

# Let the Cloud Run service itself (the default compute service account,
# unless you set a dedicated runtime SA) read the DB secret
RUNTIME_SA="$(gcloud iam service-accounts list --filter='displayName:"Default compute"' --format='value(email)')"
gcloud secrets add-iam-policy-binding buurtkompas-database-url \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor

# Workload Identity Federation: lets GitHub Actions authenticate without a
# downloaded JSON key, scoped to only this repo
gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --display-name="GitHub" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

POOL_ID="$(gcloud iam workload-identity-pools describe github --location=global --format='value(name)')"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${REPO}"
```

Note the `attribute.repository/${REPO}` condition on the last command — this
is what stops any *other* GitHub repo from being able to impersonate this
service account, not just this one being able to. Skipping it (binding the
whole pool rather than a specific repo's identity) is the single most common
Workload Identity Federation misconfiguration.

Then set these as GitHub **repository variables** (Settings → Secrets and
variables → Actions → Variables — not Secrets, since none of these values
are sensitive on their own):

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | your GCP project ID |
| `GCP_WIF_PROVIDER` | `gcloud iam workload-identity-pools providers describe github --location=global --workload-identity-pool=github --format='value(name)'` |
| `GCP_DEPLOY_SA` | `buurtkompas-deployer@<project-id>.iam.gserviceaccount.com` |

## 4. First deploy

Push a change under `src/buurtkompas/dashboard/` to `main` (or trigger
`.github/workflows/deploy-cloudrun.yml` manually from the Actions tab). The
workflow builds the image, pushes it to Artifact Registry, and deploys it to
Cloud Run with `DATABASE_URL` injected from Secret Manager. The deployed URL
is printed in the `deploy-cloudrun` step's output and also visible under
Cloud Run in the GCP Console.

## Simpler alternative to Workload Identity Federation

If the WIF setup above is more than you want to do up front, `auth@v2` also
accepts a downloaded service-account JSON key via `credentials_json:
${{ secrets.GCP_SA_KEY }}` instead of `workload_identity_provider`/
`service_account`. It's faster to set up but leaves a long-lived credential
sitting in GitHub Secrets that has to be rotated manually — fine to start
with, worth migrating to WIF once the rest of the pipeline is working.

## Cost / cleanup notes

- Cloud Run's `--min-instances=0` means it scales to zero and costs nothing
  while nobody's looking at it — the free grant above covers realistic
  portfolio-demo traffic with room to spare.
- Neon's free-tier compute autosuspends after 5 minutes idle; the first
  request after a quiet spell will be a few seconds slower while it wakes up
  (worth mentioning up front if you're demoing this live).
- Nothing in this setup uses a paid tier by default. If a future step (e.g.
  a custom domain, or exceeding the free grants) would introduce a real
  charge, that'll be called out explicitly rather than silently enabled.

## What was and wasn't verified before delivery

- The Dockerfile's actual `docker build` could not be run in the sandbox
  this was developed in (its network policy blocks Docker Hub/GHCR image
  pulls) — this is a sandbox restriction, not a Dockerfile issue, but it
  does mean the build itself needs to be verified on your machine or by
  the GitHub Actions run, not just trusted from here.
- What *was* verified end-to-end: the exact command the container's `CMD`
  runs (`streamlit run ... --server.port=$PORT --server.address=0.0.0.0`)
  was run directly (outside a container) against a real PostGIS-backed
  Postgres populated by the actual Extract→Load→dbt pipeline, and confirmed
  to serve HTTP 200 and render the choropleth/ranked table correctly. That
  covers the part of the Dockerfile most likely to silently break
  (Cloud Run's `$PORT`/`0.0.0.0` requirement) — the remaining risk is
  narrower dependency-resolution issues in the `uv sync` layers, which only
  a real `docker build` will catch.

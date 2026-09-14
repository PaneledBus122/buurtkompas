# Dashboard-only image (Phase 6): serves src/buurtkompas/dashboard/app.py on
# Cloud Run. Deliberately does NOT include geopandas/GDAL -- those are only
# needed by the Load step (run separately, on demand, against Neon), so
# keeping them out of this image keeps it small and avoids GDAL's system
# library requirements inside the container entirely.
FROM python:3.12-slim

# Installed from PyPI (rather than copied from astral-sh's own image) so
# this build doesn't depend on ghcr.io being reachable from wherever it runs.
RUN pip install --no-cache-dir uv==0.8.17

WORKDIR /app

# Dependencies first, in their own layer, so editing application code below
# doesn't invalidate (and re-download) this layer on every rebuild.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# Cloud Run injects $PORT at runtime (defaults to 8080 locally) and routes
# traffic to it -- Streamlit's own default (localhost:8501) would make the
# service unreachable, so both host and port are pinned explicitly below.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "streamlit run src/buurtkompas/dashboard/app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]

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

COPY README.md ./
COPY src/ src/
COPY .streamlit/ .streamlit/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# Pre-download the NLU model at build time so the running container never
# needs network access to Hugging Face. Imports the model id from the
# classifier module itself (rather than repeating the string here) so this
# can't silently drift from what the app actually loads at runtime.
RUN python -c "from buurtkompas.nlu.classifier import _MODEL_NAME; from sentence_transformers import SentenceTransformer; SentenceTransformer(_MODEL_NAME)"

# Forces the app to use the cache baked in above instead of checking Hugging
# Face for updates on every cold start -- without this, huggingface_hub
# still makes a network call before falling back to the local cache. Must
# come after the download above, which needs the network.
ENV HF_HUB_OFFLINE=1

# Cloud Run injects $PORT at runtime (defaults to 8080 locally) and routes
# traffic to it -- Streamlit's own default (localhost:8501) would make the
# service unreachable, so both host and port are pinned explicitly below.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "streamlit run src/buurtkompas/dashboard/app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --server.fileWatcherType=none --browser.gatherUsageStats=false"]

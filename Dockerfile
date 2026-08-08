# syntax=docker/dockerfile:1

# ============================================================================
# Stage 1: Builder — installs dependencies into an isolated virtualenv.
# build-essential lives ONLY here. In a multi-stage build this stage is
# discarded entirely after COPY --from=builder below, so keeping it as a
# defensive default (e.g. for pydantic-core, a transitive google-genai dep,
# on platforms without a prebuilt wheel) costs zero bytes in the final image.
# ============================================================================
FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage 2: Runtime — minimal final image. No compiler, no pip cache,
# no build tooling — just the venv and the application source.
# ============================================================================
FROM python:3.12-slim-bookworm AS runtime

# Non-root user, UID/GID 1000 — the most common first-user default on
# Linux hosts and Docker Desktop's typical bind-mount mapping, chosen to
# maximize the odds that ./output and ./newsletters volume mounts (see
# docker-compose.yml) are writable out of the box. See the README note
# on the one known edge case where this still needs a manual fix.
RUN groupadd --system --gid 1000 app && \
    useradd --system --uid 1000 --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Source copied after dependencies are installed above, so editing
# application code never invalidates the (expensive) pip install layer.
COPY --chown=app:app . .

# Created up front so the non-root user always has a writable target even
# before docker-compose's volume mounts attach over these same paths.
RUN mkdir -p output newsletters && chown -R app:app output newsletters

USER app

EXPOSE 8501

# Streamlit's own health endpoint. Defined here (not duplicated in
# docker-compose.yml) so it travels with the image regardless of how it's
# run — plain `docker run`, compose, or a future orchestrator.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3)" || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true"]
# SENTINEL in one container, for Google Cloud Run or any Docker host.
# The Next.js web app serves $PORT (Cloud Run sets 8080) and forwards /api/* to the
# FastAPI backend, which runs inside the same container on 127.0.0.1:8000.

# ---- Web app: install, type-check and build, then keep only runtime packages
FROM node:22-bookworm-slim AS web
WORKDIR /app/command-center/frontend
COPY command-center/frontend/package.json command-center/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY command-center/frontend/ ./
# The /api proxy target is fixed when the web app is built.
ENV NEXT_TELEMETRY_DISABLED=1 SENTINEL_API_ORIGIN=http://127.0.0.1:8000
RUN npm run build && npm prune --omit=dev

# ---- Runtime: Python backend with the frozen models, plus the built web app
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    SENTINEL_API_ORIGIN=http://127.0.0.1:8000 \
    SENTINEL_STORE=/tmp/sentinel-store \
    SENTINEL_CACHE_DIR=/tmp/sentinel-cache \
    SENTINEL_LOCAL_PATHS=dataset \
    PORT=8080
# Same Debian release as the build stage, so the Node binary's libraries match.
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY command-center/backend/requirements.txt command-center/backend/requirements.txt
RUN pip install -r command-center/backend/requirements.txt
COPY command-center/backend command-center/backend
COPY artifacts artifacts
COPY reports/validation reports/validation
COPY --from=web /app/command-center/frontend command-center/frontend
COPY deploy/start.sh deploy/start.sh
RUN useradd --uid 10001 --create-home sentinel \
    && chown -R sentinel /app/command-center/frontend/.next
USER sentinel
EXPOSE 8080
CMD ["sh", "/app/deploy/start.sh"]

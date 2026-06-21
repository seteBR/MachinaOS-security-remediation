FROM ghcr.io/astral-sh/uv:0.9.18 AS uv-bin

FROM node:22-bookworm-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVE_STATIC_CLIENT=true \
    HOST=0.0.0.0 \
    PORT=3010 \
    DATA_DIR=/data \
    NODEJS_EXECUTOR_HOST=127.0.0.1 \
    NODEJS_EXECUTOR_PORT=3020 \
    NODEJS_EXECUTOR_URL=http://127.0.0.1:3020

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /uvx /usr/local/bin/

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml pyproject.toml .npmrc ./
COPY client/package.json ./client/package.json
COPY server/package.json server/pyproject.toml ./server/
COPY server/nodejs/package.json ./server/nodejs/package.json

RUN MACHINAOS_BUILDING=true pnpm install --frozen-lockfile

COPY . .

RUN pnpm --filter react-flow-client run build \
    && pnpm --filter machinaos-nodejs-executor run build \
    && uv sync --project server --no-dev \
    && /app/server/.venv/bin/python -O -m compileall -q server

COPY docker/entrypoint.sh /usr/local/bin/machinaos-entrypoint
RUN chmod +x /usr/local/bin/machinaos-entrypoint

VOLUME ["/data"]
EXPOSE 3010

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null || exit 1

ENTRYPOINT ["machinaos-entrypoint"]

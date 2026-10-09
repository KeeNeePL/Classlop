# syntax=docker/dockerfile:1
FROM python:3.13-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.13-slim
WORKDIR /app
COPY --from=backend /app /app
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8000
CMD ["classlop", "web"]

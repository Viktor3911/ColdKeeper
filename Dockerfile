# Backend image: API, worker, CLI and simulator share it (different commands in docker-compose.yml).
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.13.16-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first (cached layer), installed strictly from uv.lock without dev tools.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY backend ./backend
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 coldkeeper \
    && mkdir -p /app/.demo \
    && chown coldkeeper /app/.demo
USER coldkeeper

EXPOSE 8000
CMD ["uvicorn", "--factory", "backend.interfaces.http.app:create_production_app", "--host=0.0.0.0", "--port=8000"]

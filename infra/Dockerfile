# One image for all four services (plan §6: the same core library in every deployable
# service). Each service picks its own command and receives only its own settings at run
# time; no env files, keys, private data or benchmark labels are ever baked in (.dockerignore).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Locked, production dependencies only (no pytest/ruff).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY apps ./apps
COPY prompts ./prompts
COPY catalog ./catalog
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# Overridden per service in infra/compose.yml.
CMD ["foodvision", "--help"]

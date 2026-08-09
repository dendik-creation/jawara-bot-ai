FROM python:3.14-slim

# uv is copied from its own released image rather than pip-installed: the version
# is pinned, and the image's pip is never used.
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/

WORKDIR /app

# Install into the system interpreter, not a project .venv, so `uvicorn`,
# `celery` and the compose healthcheck's `python -c ...` all work without a
# wrapper or an activated environment.
ENV UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependencies first: they change far less often than app code, so this layer
# survives most rebuilds.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

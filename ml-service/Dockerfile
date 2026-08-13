FROM python:3.14-slim

# See backend/Dockerfile for why uv arrives this way.
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/

WORKDIR /app

# tesseract-ocr: the binary pytesseract shells out to (app/models/ocr.py).
# -ind/-eng: language data for the two languages OCR is documented to
# support. No other language packs — each one is more image in a container
# that otherwise has none of this weight.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ind \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

# Single worker by default: model instances live in process memory, and a second
# uvicorn worker doubles that cost for no throughput gain on a CPU-bound
# workload. Scale with `docker compose up --scale ml-service=N` instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]

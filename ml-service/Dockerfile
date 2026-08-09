FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Single worker by default: model instances live in process memory, and a second
# uvicorn worker doubles that cost for no throughput gain on a CPU-bound
# workload. Scale with `docker compose up --scale ml-service=N` instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]

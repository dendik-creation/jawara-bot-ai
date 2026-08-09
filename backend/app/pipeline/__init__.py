"""Message-processing pipeline stages owned by the gateway/worker.

Stage 4 of 02_Architecture/02_Data_Pipeline.md: normalisation, indicator
extraction, deterministic Detection Rules, and intent routing. Anything that
needs a model (OCR, embeddings, generation) lives in `ml-service/` and is
reached through `app.clients.ml_client` — never imported here.
"""

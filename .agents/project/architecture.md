# system architecture

modular monolith. self-hosted docker.

## layer 1: presentation
whatsapp user. waha container. nextjs 14 dashboard.

## layer 2: gateway
fastapi webhook. redis rate limit. redis broker. celery worker.

## layer 3: core ai
easyocr. virustotal. cekrekening db. llamaindex rag. jawara llm prompt.

## layer 4: data
qdrant vector db. postgres 16 relational. external api.

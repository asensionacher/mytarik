SHELL := /bin/bash

# Ingest HS codes into Qdrant.
#
# Default path is through Docker so you don't need a local Python 3.11 venv
# (the Dockerfile pins torch==2.2.2, which has no wheels for Python 3.14).
#
# If you DO have a local venv with the requirements installed, run
# `make ingest-local` instead.

ingest:
	docker compose --profile init run --rm tariffai-init

ingest-local:
	cd tariffai && python -m scripts.ingest_hs_codes

# Build only the tariffai image (useful after editing the ingest script)
build-tariffai:
	docker compose build tariffai-api

up:
	docker compose up -d qdrant tariffai-api

down:
	docker compose down

# Repository guide

## Boundaries and entry points

- `docker-compose.yml` is the only orchestrator. Services are `webapp-frontend` (Vite/Nginx, host `:3000`), `webapp-backend` (FastAPI, `:8005`), `tariffai-api` (FastAPI, `:8004`), and `qdrant` (`:6333`).
- `webapp/backend/app/main.py` owns invoice parsing, request validation, and the NDJSON progress protocol. `webapp/backend/app/invoice_parser.py` only extracts descriptions; `webapp/backend/app/tariffai_client.py` is the HTTP boundary to TariffAI.
- `tariffai/app/main.py` exposes `/classify` and `/classify/batch`; `tariffai/app/graph.py` runs preprocess → retrieval → LLM classification. Qdrant stores only the HS catalogue, not invoices or results.
- `tariffai/app/customs/` is the customs measures engine: `geography.py` (territorial validation), `taric_client.py` (real-time providers + daily TTL cache), `parser.py` (raw TARIC → contract), `knowledge.py` (non-tariff regulatory rules), `interpreter.py` (LLM summary), `service.py` (orchestrator), `router.py` (`POST /customs/evaluate`). `webapp/backend/app/main.py` publishes it as `POST /api/v1/customs/evaluate-operation`.
- No invoice/result persistence exists. Frontend state is request-local; do not add persistence assumptions without an explicit requirement.

## Commands

```bash
# Frontend: from webapp/frontend
npm ci
npm run typecheck
npm test
npm run build

# Backend: from webapp/backend, in a Python 3.11/3.12 venv
python -m pip install -r requirements.txt pytest
python -m pytest tests -v

# TariffAI: from tariffai, in a Python 3.11/3.12 venv
python -m pip install -r requirements.txt pytest
python -m pytest tests -v
python tests/test_preprocessor.py  # dependency-free Stage 1 checks

# Runtime and catalogue
make up
make ingest
make down
docker compose up -d --build
```

- `pytest` is not listed in either Python requirements file; install it separately. The host may expose only `python3`, and `torch==2.2.2` has no Python 3.14 wheels.
- There is no Python linter/typechecker, CI, or pre-commit setup. The frontend has no linter either; `npm run typecheck` is the TypeScript contract check.
- Frontend tests use `node:test` on `tests/*.test.mjs`; there is no Jest/Vitest or React component-test harness.

## Contract invariants

- The webapp→TariffAI payloads are strict: `extra="forbid"`. Provider/model selection and Azure key overrides must not be reintroduced; Azure access uses managed identity only.
- Invoice routes carry one `trade` context (`trade_mode`, `origin_country`, `dispatch_country`) for the whole invoice: a nested `trade` object in JSON bodies, flat form fields in the multipart upload, and the same nested object towards TariffAI.
- NDJSON events are `stage`, `ready`, `item`, `done`, and `error`. `item.index` may arrive out of order; the frontend reorders by index and must preserve `line_number`. A stream is incomplete without `done`.
- Frontend types in `webapp/frontend/src/types.ts` mirror backend wire shapes. Update both sides and the relevant API tests when changing a contract.
- UI strings live in `webapp/frontend/src/i18n/strings.ts`; `dict.es` and `dict.en` must retain the same shape. Add translations in both languages.
- HS codes are 6 digits. The app may show an original suggestion, but user-accepted/manual codes are review state only; no endpoint persists the override.
- The customs operation contract carries `operation_type`, `origin_country`, `destination_country`, `incoterm`, `language` and `items[]` with a 10-digit `taric_code`. It is strict (`extra="forbid"`) on both sides: `webapp/backend/app/customs_client.py` mirrors `tariffai/app/customs/schemas.py`.
- The customs cache key is `f"{taric_code}:{origin}:{destination}:{operation_type}:{date.today()}"`: the TARIC changes once a day, so a 24 h TTL is enough and the date rollover invalidates it.

## Operational gotchas

- Never run `docker compose down -v` unless the HS catalogue may be deleted. Qdrant data is in the persistent `mytarik_qdrant_data` volume.
- First-time catalogue ingestion is `docker compose --profile init run --rm tariffai-init` (`make ingest`); it downloads the HS CSV and generates embeddings, so it is slow and must run against healthy Qdrant.
- Azure Foundry and Translator require a host with system-assigned managed identity and the documented Azure roles. `/health` only proves the service process and Qdrant are reachable, not that Foundry/Translator calls succeed.
- If `TARIFFAI_TIMEOUT` is increased, also increase `proxy_read_timeout` in `webapp/frontend/nginx.conf`.
- `docker compose up -d --build` is required after source changes; the service images do not bind-mount source or copy the test directories.

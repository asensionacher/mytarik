# Mytarik — Runbook local

## Arranque completo

```bash
cd /home/seby/mytarik
./deploy/start_local.sh
```

El script levanta Docker, el proxy Docker→Laguna y Laguna, y espera a que la API esté sana.

## Comprobación

```bash
./deploy/healthcheck.sh
```

Debe devolver `OK` para Qdrant, TariffAI, Backend, Frontend y Laguna.

## Parada

```bash
./deploy/stop_local.sh
```

## Servicios

```text
Frontend       http://127.0.0.1:3000
Backend        http://127.0.0.1:8005
TariffAI       http://127.0.0.1:8004
Qdrant         http://127.0.0.1:6333
Laguna         http://127.0.0.1:8084/v1
Proxy Docker   http://127.0.0.1:8082/v1
```

## Modelo

```bash
/home/seby/llama.cpp/start-laguna.sh
```

Laguna usa 64K, `--reasoning off`, tres GPUs y expertos en CPU.

## TARIC diario

```bash
/home/seby/.venvs/mytarik-eu/bin/python \
  tariffai/scripts/download_taric.py --daily \
  --out /home/seby/taric/latest_daily.zip
```

## TARIC completo

El ZIP completo se descarga una vez desde CIRCABC y se pasa al script:

```bash
/home/seby/.venvs/mytarik-eu/bin/python \
  tariffai/scripts/download_taric.py \
  --full-zip /home/seby/taric/TARIC_FULL.zip
```

## Tests

```bash
cd /home/seby/mytarik
/home/seby/.venvs/mytarik-eu/bin/python -m pytest -q \
  tariffai/tests/test_eu_classifier.py \
  tariffai/tests/test_eu_retriever.py \
  tariffai/tests/test_hs6_lookup.py
```

## Evaluación sintética

```bash
cd /home/seby/mytarik
/home/seby/.venvs/mytarik-eu/bin/python \
  tariffai/scripts/eval_synthetic_documents.py \
  --mode upload --include 01 --limit 1
```

## Backup

Los datos de Qdrant están en el volumen `mytarik_qdrant_data`. No ejecutar:

```bash
docker compose down -v
```

Los snapshots se guardan en `/home/seby/backups/`.

# Estado del proyecto — 15/11/2026 13:23

## Datos cargados

```text
TARIC eu_taric:        25.878 códigos
Medidas SQLite:        1.225.487
EBTI:                  123.458 (green)
Corpus público:        1.508 documentos
TED:                   541 PDFs
SROIE:                 958 imágenes
CORD:                  6 parquet
Facturas italianas:    3 ZIP (CC BY 4.0)
Facturas sintéticas:   100 PDFs / 282 líneas
```

## Evaluación

```text
Parser:                100/100 documentos
Recuento de líneas:    100/100
Descripciones:         276/282 (97,9%)
Clasificación sintética: 8/10 CN8
Error confiado:        1 (confianza 0,9776)
T5 documentos reales:  3/10 CN8
```

## Backups

```text
/home/seby/backups/pre-windows-20261115-132324/
```

Incluye:

```text
worktree tar.gz
worktree.diff
git-status.txt
taric_measures_2026.sqlite
Nomenclature EN.xlsx
corpus_manifest.jsonl
tariff_queue.jsonl
ground_truth.jsonl
informe-sergi-2026-11-15.pdf
Qdrant snapshots
```

## Servicios

Parados antes de apagar. Para reanudar:

```bash
cd /home/seby/mytarik
./deploy/start_local.sh
```

o:

```bash
docker compose up -d
nohup /home/seby/.local/bin/mytarik_llm_proxy.py >/tmp/mytarik-llm-proxy.log 2>&1 &
nohup /home/seby/llama.cpp/start-laguna.sh >/tmp/laguna-server.log 2>&1 &
```

## Pendiente

```text
1. Reranking y calibración del clasificador.
2. Revisar 1.012 documentos de la cola.
3. Validar etiquetas contra TARIC.
4. Conectar medidas SQLite al CustomsPanel.
5. No hay commit.
```

## Rutas

```text
Corpus:       /home/seby/mytarik/data/public/corpus_manifest.jsonl
Cola:         /home/seby/mytarik/data/labeling/tariff_queue.jsonl
Sintéticas:   /home/seby/mytarik/data/synthetic/invoices/
Evaluación:   /home/seby/mytarik/docs/SYNTHETIC_EVAL.md
Informe:      /home/seby/Documentos/informe-sergi-2026-11-15.pdf
```

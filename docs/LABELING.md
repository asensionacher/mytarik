# Corpus público y etiquetado

## Corpus actual

```text
TED PDF:       539
SROIE imágenes: 344
CORD parquet:    6
Total:         889
```

Índice:

```text
data/public/corpus_manifest.jsonl
```

Campos:

```text
document_id
source
country
type
title
path
bytes
sha256
license
pii
tariff_relevance
notes
```

## Separación por tipo

```text
procurement_notice  539
receipt             344
receipt_dataset       6
```

## Separación por licencia

```text
TED open data / EU legal notice
SROIE dataset terms
CORD dataset card
```

Las licencias de SROIE y CORD están marcadas como **verificar antes de redistribuir**. No se redistribuyen; solo se usan localmente para entrenamiento.

## Cola de etiquetado

```text
data/labeling/tariff_queue.jsonl
395 documentos
```

La cola **no contiene etiquetas**. Contiene:

```text
document_id
source
type
path
excerpt
priority
expected_cn8: null
expected_taric10: null
status: pending_human_review
```

## Regla

```text
No se asigna CN8/TARIC10 por nombre de archivo.
No se asigna por LLM sin revisión.
Solo se etiqueta después de leer las líneas de producto.
```

## Qué falta

```text
1. Redactar PII de SROIE/CORD antes de entrenar.
2. Extraer líneas de producto.
3. Revisar 395 documentos.
4. Validar los códigos contra TARIC.
5. Separar train/val/test por proveedor/plantilla.
```

## Nota

Los documentos TED son noticias de contratación, no facturas. No deben usarse para etiquetas arancelarias; sí para OCR, layout y multiidioma.

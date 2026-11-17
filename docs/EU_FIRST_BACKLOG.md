# Backlog EU-first — Mytarik

Regla principal:

```text
CN8/TARIC10 = operativa diaria
HS6         = consulta internacional explícita, nunca clasificación
```

No se debe modificar el clasificador para que siga usando HS6. La migración es por
fases y cada fase debe dejar tests y no romper la web.

## Estado de partida

- La app local funciona con HS6 (5.613 códigos) y traducción local.
- `TRANSLATION_PROVIDER=local_mt` está integrado.
- El pack sintético `docs/synthetic-documents/` usa CN8/TARIC10.
- Hay cambios locales sin commit; no mezclar con la migración EU sin revisarlos.

## T1 — Modelo y parser de TARIC EU

**Objetivo:** crear la base para ingerir la nomenclatura oficial EU sin tocar aún
el clasificador.

Entregables:

```text
tariffai/app/eu_taric/__init__.py
tariffai/app/eu_taric/models.py
tariffai/app/eu_taric/parser.py
tariffai/app/eu_taric/README.md
tariffai/tests/test_eu_taric_parser.py
tariffai/tests/fixtures/taric_goods_sample.xlsx
```

Requisitos:

- Leer un XLSX de TARIC (`Goods_Nomenclature_*.xlsx`) con columnas reales.
- Normalizar `cn8` (8 dígitos) y `taric10` (10 dígitos).
- Guardar descripción, fechas de vigencia, jerarquía y código padre.
- No escribir en Qdrant todavía.
- No usar HS6 como sustituto.
- Tests con un fixture pequeño; no descargar datos en tests.

Aceptación:

```text
pytest tariffs... test_eu_taric_parser.py
```

## T2 — Ingesta EU en Qdrant

**Objetivo:** crear `eu_taric` con embeddings y metadatos, sin tocar `hs_codes`.

Entregables:

```text
tariffai/scripts/ingest_eu_taric.py
```

Requisitos:

- Leer el JSON/CSV generado por T1.
- Crear colección `eu_taric` (no `hs_codes`).
- Payload: `cn8`, `taric10`, descripciones ES/EN, capítulo, partida, fechas.
- No meter códigos HS6 en el payload operativo.
- Documentar comando y fuente oficial.
- Idempotente: recrear o actualizar sin duplicar.

## T3 — Clasificador EU-only

**Objetivo:** que la operativa use solo CN8/TARIC10.

Cambios:

```text
tariffai/app/hs_retriever.py       → eu_retriever.py
tariffai/app/llm_classifier.py     → candidatos EU
tariffai/app/schemas.py            → cn8/taric10 como salida principal
tariffai/app/main.py               → contratos
webapp/backend/app/main.py         → serialización
webapp/frontend/src/types.ts       → tipos
webapp/frontend/src/...            → tabla y detalle
```

Reglas:

- El prompt no recibe `hs6`.
- La salida principal es `cn8` y `taric10`.
- HS6 no se muestra en la tabla operativa.
- No fallback a `hs_codes`.
- Tests contractuales actualizados.

## T4 — Consulta internacional separada

**Objetivo:** permitir que el usuario consulte HS6 solo si lo pide.

Entregables:

```text
GET /api/v1/reference/hs6/{code}
GET /api/v1/reference/hs6?q=...
```

Requisitos:

- Leer solo `hs6_reference` (la antigua colección `hs_codes` archivada).
- No llamar al clasificador.
- No mezclar resultados con la operativa EU.
- Pantalla/modal separada: “Consulta internacional”.
- Aviso visible: “Código internacional; no aplicable a la operativa EU”.

## T5 — Pruebas con documentos sintéticos

**Objetivo:** validar extracción, CN8/TARIC y medidas con el pack.

- Subir `01_commercial_invoice_CN_ES.pdf`.
- Comprobar 4 líneas y totales contra `ground_truth.json`.
- Verificar CN8/TARIC en la salida.
- Probar factura intra-UE y CMR.
- No aceptar HS6 en los resultados operativos.

## T6 — Servicio local reproducible

**Objetivo:** que el entorno local no dependa de pasos manuales.

- Incluir el proxy Docker→Qwen en el repo (`scripts/local_llm_proxy.py`).
- Documentar `LLM_PROVIDER=local`, `TRANSLATION_PROVIDER=local_mt`.
- Añadir healthchecks y comandos de arranque.
- No incluir secretos.

## Orden de ejecución

```text
1. T1 parser
2. T2 ingesta
3. T3 clasificador EU
4. T4 consulta internacional
5. T5 pruebas sintéticas
6. T6 reproducibilidad
```

## Reglas para OpenCode

- Leer `AGENTS.md` y este archivo antes de tocar código.
- No hacer commit ni push sin revisión.
- No modificar `hs_codes` ni borrar el volumen de Qdrant.
- No reintroducir Azure como dependencia obligatoria.
- No usar HS6 en el clasificador operativo.
- Si falta el XLSX oficial, usar un fixture y dejar el parser preparado; no inventar códigos.
- Ejecutar tests y pegar salida.

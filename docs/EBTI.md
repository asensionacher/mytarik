# EBTI — European Binding Tariff Information

## Qué es

EBTI es la base pública de **decisiones vinculantes de clasificación arancelaria**
(Binding Tariff Information) emitidas por las administraciones aduaneras de la UE.

No es el catálogo TARIC. Es jurisprudencia administrativa:

```text
TARIC / CN8  → nomenclatura y medidas
EBTI         → decisiones concretas sobre productos concretos
```

Por eso Mytarik la guarda en una colección separada:

```text
eu_taric        → catálogo operativo
ebti_decisions  → decisiones de apoyo, ejemplos y trazabilidad
```

## Fuente oficial

La Comisión Europea publica un ZIP completo y una actualización diaria:

```text
https://ec.europa.eu/taxation_customs/dds2/ebti/ebti_consultation.jsp?Lang=en
```

Enlaces:

```text
Download All BTIs:
https://ec.europa.eu/taxation_customs/dds2/ebti/ebti_export_management.jsp?message=extractFull

Download latest daily update:
botón "Download latest daily update" de la misma página
```

El ZIP completo contiene un CSV por año:

```text
EBTI_2004.csv ... EBTI_2026.csv
```

Columnas principales:

```text
BTI_REFERENCE
ISSUING_COUNTRY
START_DATE_OF_VALIDITY
END_DATE_OF_VALIDITY
NOMENCLATURE_CODE
CLASSIFICATION_JUSTIFICATION
STATUS
INVALIDATION_REASON
INVALIDATION_JUSTIFICATION
LANGUAGE
PLACE_OF_ISSUE
DATE_OF _ISSUE
NAME_AND_ADDRESS
DESCRIPTION_OF_GOODS
KEYWORDS
```

## Programa

```bash
cd /home/seby/mytarik

# Contar sin cargar nada
python3 tariffai/scripts/ingest_ebti.py \
  --zip /home/seby/ebti/ebti_full.zip --dry-run

# Probar 100 registros
python3 tariffai/scripts/ingest_ebti.py \
  --zip /home/seby/ebti/ebti_full.zip --limit 100

# Carga completa (solo válidos y países UE)
python3 tariffai/scripts/ingest_ebti.py \
  --zip /home/seby/ebti/ebti_full.zip \
  --collection ebti_decisions --recreate

# Incluir históricos no UE (por ejemplo GB)
python3 tariffai/scripts/ingest_ebti.py \
  --zip /home/seby/ebti/ebti_full.zip \
  --include-non-eu --recreate
```

## Filtros por defecto

```text
STATUS = VALID
ISSUING_COUNTRY en la UE-27
Deduplicación por BTI_REFERENCE
```

## Advertencia legal

EBTI está publicado por la Comisión Europea, pero su reutilización debe respetar
la [política de reutilización](https://ec.europa.eu/info/legal-notice_en) y la
normativa de protección de datos. No es asesoramiento jurídico ni sustituye una
decisión vinculante de la autoridad aduanera.

La clasificación final debe ser validada por un agente de aduanas.

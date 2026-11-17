# EU TARIC — Goods Nomenclature

Parser offline de la nomenclatura de la Unión Europea.

## Fuente

La Comisión Europea publica la Goods Nomenclature de TARIC en XLSX con estas
columnas:

```text
GOODS CODE
START_DATE
END_DATE
LANG_COD
HIER_POS
INDENTS
DESCR_TEXT
PUBLISH
DESCR_START_DATE
REC_SEQ_NUM
```

- [TARIC consultation](https://ec.europa.eu/taxation_customs/dds2/taric/taric_consultation.jsp?Lang=en)
- [TARIC Full database](https://circabc.europa.eu/ui/group/0e5f18c2-4b2f-42e9-aed4-dfe50ae1263b/library/64db9d0f-e7c9-4084-afe9-f47e70e53c10?p=1&n=-1&sort=name_ASC)

## Niveles

```text
2 dígitos   capítulo
4 dígitos   partida
6 dígitos   subpartida del Sistema Armonizado
8 dígitos   CN8 (operativo en la UE)
10 dígitos  TARIC10 (código integrado y medidas)
```

El parser conserva los niveles 2/4/6 para la jerarquía, pero **solo 8/10 son
códigos operativos**. El flujo de Mytarik no debe clasificar con HS6.

## Uso

```python
from app.eu_taric import parse_goods_nomenclature_xlsx

entries = parse_goods_nomenclature_xlsx("Goods_Nomenclature_20261112_1914.xlsx")
for entry in entries:
    if entry.cn8:
        print(entry.cn8, entry.taric10, entry.description)
```

## Reglas

- `GOODS CODE` se normaliza a dígitos, conservando ceros a la izquierda.
- Longitudes válidas: 2, 4, 6, 8 y 10.
- Un código de 8 dígitos produce `cn8`; uno de 10 produce `cn8` y `taric10`.
- Las fechas se normalizan a ISO `YYYY-MM-DD`.
- No se descarga nada ni se escribe en Qdrant.
- Los tests usan un fixture local y no dependen de red.

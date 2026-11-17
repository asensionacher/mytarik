# Paquete de documentos sintéticos — Comercio exterior UE

**Pack:** `EU-SYN-2026-11`  
**Fecha:** 13 de noviembre de 2026  
**Uso:** pruebas de Mytarik, extracción, clasificación y medidas aduaneras.

> **Aviso:** todos los nombres, direcciones, EORI, VAT, bancos, contenedores y firmas son ficticios. Los documentos llevan la marca `SPECIMEN` y no son válidos para despacho aduanero ni para uso comercial.

## Documentos incluidos

| Archivo | Documento | Escenario |
|---|---|---|
| `01_commercial_invoice_CN_ES.pdf` | Factura comercial | Importación China → España, CIF Valencia |
| `02_packing_list_CN_ES.pdf` | Packing list | Ligado a la factura anterior |
| `03_bill_of_lading_CN_ES.pdf` | Bill of Lading | Transporte marítimo Ningbo → Valencia |
| `04_eu_import_declaration_SAD.pdf` | Declaración de importación UE (extracto SAD/DAU) | Despacho a libre práctica, oficina ES002001 |
| `05_certificate_of_origin_CN.pdf` | Certificado de origen no preferencial | Emitido en China; solo mercancía de origen CN |
| `06_intra_eu_invoice_DE_ES.pdf` | Factura intracomunitaria | Alemania → España, inversión del sujeto pasivo |
| `07_cmr_DE_ES.pdf` | Carta de porte CMR | Transporte por carretera Düsseldorf → Valencia |

Además:

- `ground_truth.json`: líneas, importes, pesos, CN8, TARIC10 y HS6 esperados.
- `eu_codes_sample.csv`: subconjunto de códigos UE usado en el pack.
- `generate_documents.py`: generador reproducible de los PDF.

## Diferencia importante: HS6, CN8 y TARIC10

```text
HS6      → 6 dígitos, nomenclatura internacional (prefijo)
CN8      → 8 dígitos, Combined Nomenclature de la UE (importación/exportación)
TARIC10  → 10 dígitos, arancel integrado de la UE (medidas, tipos, restricciones)
```

Ejemplo:

```text
HS6       620520
CN8       62052000
TARIC10   6205200000
```

La aplicación actual trabaja con candidatos HS6 y después expande a TARIC mediante
`/customs/resolve-taric-codes`. Para trabajar como una aplicación exclusivamente
UE, el catálogo y el resultado deben pasar a CN8/TARIC10. Este paquete ya usa
CN8 en las facturas y CN8 + TARIC10 en la declaración.

> Los sufijos TARIC10 de este pack son ilustrativos. Antes de producción hay que
> verificarlos en la base TARIC oficial para la fecha de la operación. Los CN8
> son códigos reales de la nomenclatura combinada.

## Escenario principal

```text
Exportador:  Ningbo Garment & Hardware Co., Ltd. (China)
Importador:  Ibérica Textil Import, S.L. (Valencia, España)
EORI:        ESB00000001
Factura:     EXP-2026-1042, 28/10/2026
Incoterm:    CIF Valencia (Incoterms 2020)
B/L:         COSU-SYN-2026-1042
Contenedor:  CSNU 123456 7 / Seal CN-998877
Buque:       MSC ALEXANDRIA / Voy. 642W
```

Líneas:

| # | Producto | CN8 | TARIC10 | Origen | Cantidad | Precio | Importe |
|---|---|---|---:|---|---:|---:|---:|
| 1 | Camisas de algodón para hombre | 62052000 | 6205200000 | CN | 120 | 18,50 | 2.220,00 |
| 2 | Ropa de cama de algodón | 63022100 | 6302210000 | CN | 80 | 32,00 | 2.560,00 |
| 3 | Bujías de encendido | 85111000 | 8511100000 | CN | 500 | 4,20 | 2.100,00 |
| 4 | Aceite de oliva virgen extra | 15091010 | 1509101000 | ES | 60 | 9,50 | 570,00 |

Totales:

```text
Mercancía:        EUR 7.450,00
Flete:            EUR 650,00
Seguro:           EUR 120,00
CIF Valencia:     EUR 8.220,00
Peso neto:        242,00 kg
Peso bruto:       289,60 kg
```

## Fuentes oficiales para validar

- [EU Customs Tariff](https://taxation-customs.ec.europa.eu/customs-4/calculation-customs-duties/customs-tariff/eu-customs-tariff_en)
- [TARIC consultation](https://ec.europa.eu/taxation_customs/dds2/taric/taric_consultation.jsp?Lang=en)
- [Access2Markets](https://trade.ec.europa.eu/access-to-markets/en/home)
- [EU customs declaration / SAD](https://taxation-customs.ec.europa.eu/customs-4/customs-procedures-import-and-export-0/customs-formalities/standard-customs-declaration_en)
- [Incoterms 2020 — ICC](https://iccwbo.org/business-solutions/incoterms-rules/incoterms-2020/)

## Cómo usarlo en Mytarik

1. Subir `01_commercial_invoice_CN_ES.pdf` a la UI.
2. Comprobar extracción de las cuatro líneas.
3. Clasificar por descripción.
4. Contrastar el resultado con `ground_truth.json`.
5. Resolver CN8/TARIC10 con el motor de medidas.
6. Repetir con la factura intra-UE y el CMR.

## Limitaciones

```text
No son documentos reales
No son válidos para aduanas
Los TARIC10 deben verificarse
Los tipos de derechos son ilustrativos
No se ha simulado una liquidación oficial
```

# Fidelidad del corpus sintético — base normativa y de mercado

Este documento fija **qué debe tener una factura de importación real** para que el
corpus sintético (`tools/datagen/`) no sea un juguete. No se ha descargado ninguna
factura real: las referencias son textos normativos oficiales, la nomenclatura
TARIC/CN oficial y resoluciones EBTI públicas ya presentes en el repositorio.

## 1. Contenido obligatorio de la factura (UE)

Directiva 2006/112/CE, art. 226 (15 apartados, texto consolidado):

```text
(1)  fecha de expedición
(2)  número secuencial por serie que identifique la factura
(3)  NIF-IVA del proveedor
(4)  NIF-IVA del cliente (cuando sea deudor del IVA o entrega intracomunitaria)
(5)  nombre y dirección completos de proveedor y cliente
(6)  cantidad y naturaleza de los bienes / alcance de los servicios
(7)  fecha de la operación si difiere de la de expedición
(8)  base imponible por tipo, precio unitario sin IVA, descuentos
(9)  tipo de IVA aplicado
(10) cuota de IVA repercutida
(11) referencia a la exención o a la inversión del sujeto pasivo
(12) características de medios de transporte nuevos
(13) referencia al régimen de agencias de viajes
(14) referencia al régimen de bienes usados/arte/antigüedades
(15) NIF-IVA y datos del representante fiscal
```

## 2. Contenido obligatorio en España

Real Decreto 1619/2012 (BOE-A-2012-14696), art. 6.1, letras a–p:

```text
a) número y, en su caso, serie; numeración correlativa por serie
b) fecha de expedición
c) nombre y apellidos o razón social completa de emisor y destinatario
d) NIF del emisor (y del destinatario en los supuestos del art. 6.1.d)
e) domicilio de emisor y destinatario
f) descripción de las operaciones, base imponible, precio unitario sin IVA
   y descuentos o rebajas no incluidos en el precio
g) tipo o tipos impositivos
h) cuota tributaria repercutida, por separado
i) fecha de la operación o del pago anticipado si difiere
j) referencia a la exención (art. 6.1.j)
k) características de medios de transporte nuevos
l) «facturación por el destinatario»
m) «inversión del sujeto pasivo»
n) «régimen especial de las agencias de viajes»
o) «régimen especial de los bienes usados» / «objetos de arte» / «antigüedades»
p) «régimen especial del criterio de caja»
```

El art. 6.5 (añadido por RD 1007/2023, en vigor 07/12/2023) obliga, para facturas
emitidas con sistemas informáticos de facturación, a incluir **código QR** y, si
procede, la leyenda «Factura verificable en la sede electrónica de la AEAT» o
«VERI\*FACTU». El corpus debe incluir un pequeño porcentaje con QR y sin él.

Factura simplificada (art. 7): no lleva datos del destinatario salvo que sea
empresario y los exija; no se usa para entregas intracomunitarias (art. 4.4).

## 3. Datos aduaneros que una factura comercial sí lleva

Una factura comercial de importación **no es** una declaración aduanera, pero en
tráfico extracomunitario suele incluir:

```text
Incoterm + plaza (CIF Valencia, FOB Ningbo, DAP Hamburg...)
país de origen de la mercancía (distinto del país del proveedor)
peso neto y bruto, número de bultos, tipo de embalaje
código HS/CN impreso en columna (frecuente en exportadores asiáticos; raro en
  facturas intracomunitarias)
descripción comercial + referencia/modelo + composición + presentación
condiciones de pago, banco, IBAN/SWIFT, cláusula de jurisdicción
contenedor, sello, B/L o CMR, buque/vuelo
EORI del importador (a menudo impreso para el despacho)
divisa y, si no es EUR, tipo de cambio
```

Lo que **no** debe aparecer es un CN8/TARIC10 verificado por la aduana: la
clasificación la hace el declarante. Por eso el corpus imprime códigos solo en
los diseños de importación extracomunitaria, y siempre con la marca `SPECIMEN`.

## 4. Datos identificativos: reglas de coherencia

Todas las partes son ficticias. Para que un revisor no confunda una invención con
un dato real, se aplican reglas verificables:

```text
NIF español (persona jurídica)  letra + 7 dígitos + control (algoritmo AEAT)
NIF-IVA intracomunitario         prefijo país + NIF nacional válido
EORI                             país + identificador (ES + NIF en España)
IBAN                             ES + 22 dígitos, control mod-97 correcto
BIC                             8 u 11 caracteres, estructura AAAABBCC[XXX]
USCI china                       18 caracteres, dígito 18 = control base 31
                                 (GB 32100-2015, alfabeto sin I/O/S/V/Z)
registro mercantil               tomo/folio/hoja plausibles por provincia
```

Ningún nombre de empresa real. Los nombres se generan por combinación y se
comprueba que no colisionen con una lista de empresas reales conocidas del sector.

## 5. Qué se ha tomado como «ejemplo real» sin descargarlo

```text
- Estructura y campos: art. 226 Directiva 2006/112/CE y art. 6 RD 1619/2012.
- Descripciones de mercancía: 123.458 resoluciones EBTI públicas (data/real/
  ebti_labels.jsonl), con su CN8 y TARIC10 reales. Se usan como texto de
  producto; no se copia la resolución ni datos del solicitante.
- Códigos y jerarquía: export oficial de la nomenclatura (CIRCABC 2026-10/11,
  Nomenclature EN.xlsx), 25.878 filas, niveles 2/4/6/8/10.
- Tipos de derecho, medidas y orígenes: TARIC Measures (misma fuente).
- Tipos de IVA español: 21 % general, 10 % reducido, 4 % superreducido.
- Incoterms 2020: ICC.
```

Los PDFs reales que aparecen en buscadores solo se han consultado como
referencia visual de campos y orden; **ninguno se ha descargado** ni se ha usado
como plantilla.

## 6. Consecuencias de diseño

```text
ES + EN            dos géneros: factura de importación extra-UE emitida en
                   inglés y factura intra-UE/doméstica emitida en español
25 diseños         con y sin columna de código, una y varias páginas, con QR,
                   multi-divisa, series y numeración intercalada
~20 % escaneados   PDF rasterizado 150-200 ppp con ruido, rotación y sombra
SPECIMEN           marca de agua y pie en todas las páginas
ground truth       JSON por factura + manifiesto CSV/XLSX para revisión
```

## 7. Fuentes

- Directiva 2006/112/CE — https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32006L0112
- RD 1619/2012 — https://www.boe.es/buscar/act.php?id=BOE-A-2012-14696
- TARIC / nomenclatura CN — https://ec.europa.eu/taxation_customs/dds2/taric/
- EBTI — https://ec.europa.eu/taxation_customs/dds2/ebti/
- Incoterms 2020 — https://iccwbo.org/business-solutions/incoterms-rules/incoterms-2020/
- GB 32100-2015 (USCI) — norma pública citada por los registros mercantiles chinos

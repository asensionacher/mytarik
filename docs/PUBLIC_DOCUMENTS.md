# Documentos públicos — política y primer corpus

## Fuente inicial

```text
TED — Tenders Electronic Daily
API pública, sin login
Cobertura: 27 Estados miembros
Tipo: noticias de contratación pública (PDF + XML)
Licencia: datos abiertos de la UE; verificar aviso legal TED
```

## Lo que hemos descargado

```text
Países: 27/27
PDF:    28
XML:    28
Total:  5,9 MB
Manifest: data/public/ted/manifest.jsonl
```

Cada registro guarda:

```text
país
número de publicación
tipo de noticia
título
URL
ruta local
tamaño
SHA-256
licencia
fecha de recogida
```

## Limitación importante

```text
Una noticia de contratación NO es una factura aduanera.
No contiene CN8/TARIC10 ni líneas de factura.
```

Sirve para:

```text
layout
OCR
extracción de entidades
documentos multiidioma
ruido real
```

No sirve para:

```text
entrenar la clasificación arancelaria
validar TARIC
```

## Siguiente corpus

Para facturas reales:

```text
portales de transparencia
facturas y pagos públicos
datasets de facturas
documentos anonimizados de despachos
```

## Reglas

```text
solo fuentes públicas
sin logins
sin paywalls
respetar robots.txt y términos
manifest de licencia
hash y deduplicación
anonimizar datos personales antes de entrenar
```

## Comando

```bash
python tariffai/scripts/collect_ted.py --limit-per-country 20
```

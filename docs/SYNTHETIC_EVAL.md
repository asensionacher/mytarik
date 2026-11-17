# Evaluación del lote sintético

## Lote

```text
Facturas generadas: 100
Líneas:             282
Códigos válidos:    282/282
Totales cuadrados:  100/100
```

## Parser

```text
Documentos:                 100
Documentos con error:       0
Número de líneas exacto:    100/100
Descripciones exactas:      276/282 (97,9%)
```

## Clasificación

Muestra de 10 líneas, una por factura:

```text
CN8 exactos:      8/10
TARIC10 exactos:  8/10
Sin código:       1/10
Errores:          0/10
```

Resultado peligroso:

```text
1 acierto erróneo con confianza 0,9776
```

Es un falso positivo seguro, justo el tipo de error que no puede llegar a un despacho.

## Tiempo

```text
Media: 93 s por línea
```

Clasificar 282 líneas completas tardaría unas 7 horas. No es viable para producción sin optimización.

## Conclusión

```text
El generador y el parser están bien.
El clasificador no está listo para producción.
La confianza no está calibrada.
```

## Próximos pasos

```text
1. Generar descripciones jerárquicas completas, no fragmentos como "Other".
2. Añadir umbral de abstención.
3. Repetir con 100 líneas.
4. Validar con facturas reales etiquetadas.
```

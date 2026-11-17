# Prueba de billion-context con OpenCode + Laguna

Fecha: 2026-11-15

## Instalación

```text
billion-context: 0.1.215
Node:            26.13.1 (nvm)
OpenCode:        1.19.5
Modelo:          Laguna S 2.1 Q4
Contexto:        65.536
```

Plugin nativo de OpenCode instalado y luego revertido.

## Baseline sin bili

```text
Petición:  "Responde exactamente una línea: BILI_OK"
Prompt:    ~31,5 KiB
Tiempo:    136 s
Salida:    BILI_OK
```

## Con bili

```text
Prompt de salida:     43,8 KiB  (+39%)
Compresión aplicada:  0
Uso de contexto:      0%
Motivo:               max compressible 0 < threshold 50.000
Primer byte:          >30 s
Timeout cliente:      180 s
Resultado:            abortado
```

Log relevante:

```text
nudge idle: usage=0% (41/61440), growth=0/22500,
reason="max compressible 0 < threshold 50000; growth 0 < floor 22500"
stream silent 15000ms — holding client
client disconnected mid-stream after 176267ms
```

## Diagnóstico

bili sí arrancó, interceptó el tráfico y enrutó a Laguna.
El problema no fue la instalación: fue el coste de contexto.

```text
- bili inyecta herramientas y prompt de gestión de contexto
- Laguna tiene 64K y prefill lento
- la tarea era demasiado corta para comprimir
- el prompt creció un 39%
- el modelo tardó más que el timeout
```

## Conclusión

```text
billion-context no es útil para tareas cortas con Laguna.
Puede tener sentido en sesiones >50K tokens,
pero necesita un modelo más rápido o un contexto mayor.
```

## Rollback

```text
Config de OpenCode restaurada desde:
/home/seby/backups/pre-bili-20261115-182313/opencode-config/
Plugin de OpenCode desactivado.
bili queda instalado pero sin lane activa.
```

## Recomendación

```text
No instalarlo en DSH/Hermes todavía.
Primero probar una sesión larga (>50K) y medir:
- compresión real
- tiempo hasta primer token
- calidad del resumen
- recuperación con decompress
```

## Config

```text
~/.config/billion-context/billion-context.json
```

Se eliminó `modelEndpointPatterns` porque esta versión lo rechaza.
El endpoint local se enruta por `providers`.

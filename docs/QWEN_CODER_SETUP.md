# Qwen2.5 Coder 32B + OpenCode + billion-context

## Modelo

```text
Archivo: Qwen2.5-Coder-32B-Instruct-heretic1x-general-Q4_K_M.gguf
Tamaño:  19,85 GB
Contexto nativo: 32.768 tokens
```

Instalado en:

```text
/home/seby/modelos/qwen2.5-coder-32b/
```

## Servidor

```bash
/home/seby/llama.cpp/start-qwen25-coder.sh
```

Configuración:

```text
3 GPUs, tensor split 1,1,1
ngl 99
ctx 32768
flash-attn on
KV q8_0
batch 2048 / ubatch 512
threads 14
parallel 1
temperature 0.05 en OpenCode
reasoning false
```

## Rendimiento medido

```text
Decode:  22,6 tok/s
Prefill: 250 tok/s
VRAM:    ~10 GB por GPU
```

## OpenCode

```text
Proveedor: qwen-coder
Modelo:    qwen2.5-coder-32b
Endpoint:  http://127.0.0.1:8085/v1
```

Configuración guardada en:

```text
~/.config/opencode/opencode.json
```

## billion-context

```text
Plugin nativo OpenCode: activo
Contexto:               32768
Nudge de compresión:    12000 tokens
Umbral:                 65%
Node:                   26.13.1
```

Variable necesaria:

```bash
export BILLION_CONTEXT_NODE=/home/seby/.nvm/versions/node/v26.13.1/bin/node
```

## Pruebas

### Chat simple

```text
Qwen + bili: 15 s, BILI_QWEN_OK
```

### Escritura de archivo

```text
El modelo genera:
{"name":"write","arguments":{...}}

Pero OpenCode lo recibe como texto, no como tool_call.
El archivo no se crea.
```

## Diagnóstico

```text
El modelo no usa el formato <tool_call> que espera llama.cpp/OpenCode.
El servidor devuelve ese JSON como content, no como tool_calls.
```

No es un problema de bili. Ocurre también con `--pure`.

## Conclusión

```text
Chat:          funciona
Contexto:      32K nativos + compresión bili
Código:        bloqueado por tool calling
```

## Siguiente

```text
1. Usar un GGUF Qwen2.5-Coder-Instruct oficial con tool calling.
2. O añadir un adaptador que convierta el JSON del modelo en tool_calls.
3. No usar este heretic1x-general para edición de archivos todavía.
```

## Adaptador JSON -> tool_calls

Archivo:

```text
/home/seby/.local/bin/qwen_tool_adapter.py
```

Puerto:

```text
8086
```

Flujo:

```text
OpenCode → bili 18787 → adaptador 8086 → llama.cpp 8085
```

Convierte:

```json
{"name":"write","arguments":{"filePath":"hello.py","content":"..."}}
```

en:

```json
"tool_calls": [{"id":"call_...","type":"function","function":{...}}]
```

## Prueba real

```text
Petición: crea hello.py
Resultado: archivo creado
Tiempo: 7 s
Bucle: no
```

## Lanzador

```bash
/home/seby/.local/bin/start_qwen_tool_adapter.sh
```

## Estado

```text
Qwen 8085:    activo
Adaptador:    8086 activo
bili:         18787 activo
OpenCode:     qwen-coder/qwen2.5-coder-32b
```

## Corrección del error `continuation nudge` / `stream_error`

Causa: el modelo devolvía los tags internos de bili:

```text
<acp ...>m00014</acp>
```

bili los eliminaba, se quedaba sin salida y lanzaba una continuación.

Solución aplicada en `~/.config/billion-context/billion-context.json`:

```text
compress.visibilityMarkers = false
compress.messageTimestamps = false
compress.injectNudge = false
debug.renderNone = true
```

Prueba después del cambio:

```text
Crea test.py con TEST_OK
→ archivo creado en 20 s
→ sin stream_error
```

## Entorno

```text
venv_taric activo
aiohttp, PyMuPDF, pytesseract, pydantic
OpenCode steps=12
```

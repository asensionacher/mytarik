# MyTarik — Clasificador de facturas con HS codes

Webapp que sube una factura (PDF, texto o imagen), extrae sus líneas y las clasifica en códigos arancelarios (HS code de 6 dígitos) usando la API de **[TariffAI](../tariffai/)**.

Todo se orquestra con **un único `docker-compose.yml`** en la raíz.

## Arquitectura

```
 ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
 │  webapp-frontend │ ──► │ webapp-backend   │ ──► │   tariffai-api   │ ──► Qdrant
 │  Vite + Nginx    │     │   FastAPI        │     │   FastAPI        │
 │     :3000        │ ◄── │     :8005        │ ◄── │     :8004        │     :6333
 └──────────────────┘     └──────────────────┘     └──────────────────┘
   (puerto host)          (puerto host)            (puerto host)         (puerto host)
```

Dentro de la red Docker los servicios se llaman por nombre (`tariffai-api`, `webapp-backend`, `qdrant`).

## Estructura

```
mytarik/
├── docker-compose.yml      # ← orquestador único
├── .env                    # ← endpoints Azure y deployment, sin claves
├── tariffai/               # API de clasificación HS (sub-módulo ya existente)
│   ├── Dockerfile          # añadido por este proyecto
│   ├── ...
└── webapp/
    ├── backend/            # FastAPI que parsea la factura y habla con TariffAI
    │   ├── Dockerfile
    │   ├── app/
    │   └── requirements.txt
    └── frontend/           # Vite + React + TS + Tailwind (UI en español)
        ├── Dockerfile
        ├── nginx.conf
        └── src/
```

## Requisitos

- Docker Engine 24+ con `docker compose` v2
- Un host Azure con identidad administrada del sistema habilitada y accesible desde `tariffai-api`
- El deployment `MAI-Thinking-1` en Azure Foundry y Azure Translator habilitado
- Permisos de la identidad: **Azure AI User** en el proyecto Foundry y **Cognitive Services User** en el recurso Translator
- ~6 GB de RAM disponible mientras corren los modelos de embeddings

## Puesta en marcha

### 1) Configurar variables de entorno

```bash
cp .env.example .env
```

Solo se configuran tres variables: `AZURE_AI_PROJECT_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT` y `AZURE_TRANSLATOR_ENDPOINT`. Los ejemplos incluyen
el proyecto `proj-default`, el deployment `MAI-Thinking-1` y el endpoint de
Translator facilitados. No se necesitan claves, secretos, tenant ni client ID.

La autenticación usa exclusivamente `ManagedIdentityCredential`: no hay fallback
a claves ni a `az login`. Docker local fuera de Azure no dispone de esa identidad;
ejecuta la API en un recurso Azure con identidad administrada y acceso al endpoint
de identidad desde el contenedor. La clasificación siempre usa Foundry; la UI y
las APIs JSON ya no aceptan elegir proveedor ni modelo. La traducción al inglés
usa Azure Translator Text Translation, y un fallo de traducción se devuelve como
error de clasificación en lugar de continuar con el texto original.

### 2) Levantar todo (primera vez)

```bash
# 2.1) Arrancar Qdrant y la API de TariffAI
docker compose up -d qdrant tariffai-api

# 2.2) Una sola vez: poblar Qdrant con los ~5.300 códigos HS
#       (tarda unos minutos porque descarga el CSV y genera embeddings)
docker compose --profile init run --rm tariffai-init

# 2.3) Arrancar el backend y el frontend de la webapp
docker compose up -d webapp-backend webapp-frontend
```

> 💡 La API de TariffAI se reinicia sola al terminar la ingestión (el `depends_on` con `service_healthy` lo garantiza). Tras la primera vez, basta con `docker compose up -d`.

### 3) Atajos

```bash
# levantar todo salvo la ingestión (asume Qdrant ya poblado)
docker compose up -d

# re-ingestar (borra y rellena la colección hs_codes; tarda unos minutos)
make ingest          # equivalente a: docker compose --profile init run --rm tariffai-init

# parar todo
docker compose down
```

### Persistencia de Qdrant y reinicios de la VM

Qdrant guarda sus colecciones en el volumen Docker **`mytarik_qdrant_data`**,
montado en `/qdrant/storage`. Su nombre es fijo para reutilizar los mismos datos
incluso si cambia el nombre del proyecto Compose. Los reinicios de la VM, la
recreación del contenedor y `docker compose down` no borran ese volumen.

La política `restart: unless-stopped` vuelve a arrancar Qdrant cuando arranca
Docker, siempre que no se haya detenido explícitamente. Docker debe estar
habilitado para arrancar con la VM (`sudo systemctl enable docker` en sistemas
con systemd). Si se ha ejecutado `docker compose down`, hay que volver a crear
los contenedores con `docker compose up -d`.

**No ejecutes `docker compose down -v` ni elimines el volumen** si quieres
conservar los datos. El directorio de datos de Docker debe estar en un disco
persistente de la VM, no en el disco temporal de Azure. Esta configuración no
sustituye las copias de seguridad ni protege frente a la eliminación del disco.

### Ejecutar la ingest localmente (sin Docker)

Sólo útil si tienes un venv local con `tariffai/requirements.txt` instalado bajo
**Python 3.11 o 3.12** (`torch==2.2.2` no tiene wheels para 3.14):

```bash
cd tariffai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.ingest_hs_codes
# o desde la raíz del repo, gracias al shim en scripts/ingest_hs_codes.py:
cd .. && QDRANT_HOST=localhost python -m scripts.ingest_hs_codes
```

## Uso

- **Frontend (UI):** http://localhost:3000
- **Backend API:** http://localhost:8005/docs (Swagger)
- **TariffAI:** http://localhost:8004/docs
- **Qdrant dashboard:** http://localhost:6333/dashboard

Sube una factura a la UI, espera unos segundos y verás una tabla con cada línea, su código HS sugerido, la descripción, la confianza y el razonamiento de la cadena Section → Chapter → Heading → Subheading.

La interfaz muestra la subida, la extracción de descripciones, el tiempo
transcurrido y el número real de líneas procesadas. Los resultados aparecen en
cuanto termina cada línea, sin esperar a toda la factura, y mantienen la
numeración original aunque lleguen desordenados.

El idioma seleccionado en la web se envía en cada solicitud (`language: es|en`).
Se guarda durante un año en la cookie `mytarik.lang` y se restaura al recargar;
si no hay una preferencia válida, se utiliza el idioma del navegador.
Foundry genera en ese idioma las descripciones HS, la jerarquía, las explicaciones,
los factores clave y las alternativas. Los códigos, los valores numéricos y el
texto original de la factura no se traducen. El idioma se fija al enviar la
solicitud, también para los resultados en directo; no se realiza una segunda
llamada al modelo para traducirlos. Las APIs usan `en` si se omite `language`.

Para reducir la espera, el modo en directo mantiene **hasta tres llamadas de
clasificación en paralelo por factura** y reutiliza las descripciones idénticas
dentro de la misma solicitud. No cambia el modelo ni reduce su presupuesto de
razonamiento. La mejora afecta a facturas con varias descripciones; una sola
línea sigue dependiendo de la latencia de Foundry. Si el proceso se interrumpe,
los resultados ya recibidos permanecen visibles.

## Formatos soportados en el upload

- **PDF** (texto embebido): se extraen las tablas (`pdfplumber`) y se toma la columna de descripción.
- **Texto plano** (`.txt`, `.csv`): una descripción por línea.
- **Imagen** (`.png`, `.jpg`, `.webp`): se aplica OCR con Tesseract; cada línea no vacía del texto reconocido se trata como una descripción.

## Endpoints del backend (`webapp-backend`)

| Método | Ruta                       | Descripción                                                |
| ------ | -------------------------- | ---------------------------------------------------------- |
| GET    | `/health`                  | Health-check del backend + alcanzabilidad de TariffAI      |
| POST   | `/api/invoice/upload`      | `multipart/form-data` con `file` (pdf/txt/png/jpg/webp)    |
| POST   | `/api/classify`            | `{"description": "..."}` → clasificación de una línea       |
| POST   | `/api/classify/raw`        | Pega texto directo, mismo comportamiento que un `.txt`     |

`/api/invoice/upload` y `/api/classify/raw` aceptan
`Accept: application/x-ndjson` para recibir eventos `stage`, `ready`, `item` y
`done`. Los fallos posteriores al inicio del stream se envían como eventos
`error` con `status` y `message`; no se debe considerar completa una respuesta
sin `done`. Sin ese encabezado se conserva la respuesta JSON de siempre.
Nginx tiene el buffering desactivado para entregar el progreso inmediatamente.

## Idiomas

La UI está estructurada para i18n: los textos viven en `webapp/frontend/src/i18n/strings.ts` en el objeto `es` y tienen hueco preparado para `en` (sólo hay que añadirlo cuando se quiera).

## Solución de problemas

La clasificación dispone de **600 segundos** por solicitud (el lote completo,
incluidas sus páginas), con conexión limitada a 10 segundos. El proxy Nginx espera
660 segundos para dejar que el backend devuelva un error **504** explícito si se
agota el plazo. Las comprobaciones de salud conservan un timeout corto de
3 segundos; un `/health` correcto no demuestra que Foundry o Translator respondan.
No hay reintentos automáticos de clasificación en el cliente del backend.

El plazo se puede ajustar opcionalmente con `TARIFFAI_TIMEOUT` en el `.env` de la
raíz; si se aumenta, hay que aumentar también `proxy_read_timeout` en
`webapp/frontend/nginx.conf` para que sea superior. Si sigue agotándose, revisa
`docker compose logs tariffai-api` para identificar la etapa lenta y reduce el
número de líneas por solicitud.

| Síntoma                                                            | Causa / solución                                                                                          |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `webapp-backend` loggea "TariffAI unavailable"                     | Espera a que `tariffai-api` termine su `start_period` (60s la 1ª vez mientras carga el modelo de embedding) |
| `tariffai-init` falla con `Connection refused` a Qdrant            | Asegúrate de que `qdrant` está en estado `healthy` antes de correr el init                                |
| `docker compose --profile init run --rm tariffai-init` no sale de su bucle | Es la primera vez que baja `intfloat/multilingual-e5-small` (~470 MB). Espera unos minutos; revisa el progreso con `make ingest` y comprueba que la colección llegue a 5 613 puntos con `curl -s localhost:6333/collections/hs_codes` |
| `python: command not found` al correr la ingest en local            | Tu sistema sólo expone `python3` y `torch==2.2.2` no tiene wheels para 3.14. Usa `make ingest` o crea un venv con Python 3.11/3.12 |
| Las clasificaciones devuelven `error` de autenticación o permisos | Revisa la identidad administrada del host, su acceso desde el contenedor y los roles en Foundry y Translator |
| Imágenes sin clasificar                                            | La factura es muy ruidosa o el OCR no extrajo texto claro; prueba subiendo el PDF original o limpia la imagen |
| Builds muy lentos                                                  | Las imágenes de embeddings (`sentence-transformers` + `torch`) pesan ~1.5 GB. Es normal la primera build   |

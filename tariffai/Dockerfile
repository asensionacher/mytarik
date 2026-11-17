FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# PyTorch CPU: los embeddings no usan GPU y la imagen CUDA pesa ~7 GB.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.2.2
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/

# Modelos de traducción locales (OPUS-MT/CTranslate2, ~311 MB).
# Se descargan en tiempo de build para que el contenedor arranque sin red.
RUN python scripts/download_translation_models.py

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]

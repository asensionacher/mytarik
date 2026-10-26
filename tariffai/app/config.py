import os
from dotenv import load_dotenv

load_dotenv()


# --- Qdrant ---
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = "hs_codes"

# --- Embedding ---
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
EMBEDDING_DIM = 384  # dimension for multilingual-e5-small

# --- Azure (system-assigned managed identity; no API keys) ---
AZURE_AI_PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
AZURE_AI_MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT", "MAI-Thinking-1").strip()
AZURE_TRANSLATOR_ENDPOINT = os.getenv("AZURE_TRANSLATOR_ENDPOINT", "").strip().rstrip("/")

# --- Retrieval ---
TOP_K_CANDIDATES = int(os.getenv("TOP_K_CANDIDATES", "10"))
SEMANTIC_WEIGHT = 0.6
BM25_WEIGHT = 0.4

# --- Classification ---
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))

# --- Customs measures (real-time TARIC) ---
# Access2Markets (Comisión Europea) es el proveedor principal de medidas.
A2M_BASE_URL = os.getenv(
    "A2M_BASE_URL", "https://trade.ec.europa.eu/access-to-markets"
).rstrip("/")
TARIC_HTTP_TIMEOUT = float(os.getenv("TARIC_HTTP_TIMEOUT", "20"))
TARIC_HTTP_RETRIES = int(os.getenv("TARIC_HTTP_RETRIES", "3"))
TARIC_HTTP_MAX_CONCURRENCY = int(os.getenv("TARIC_HTTP_MAX_CONCURRENCY", "5"))
# El TARIC se actualiza una vez al día: la caché vive 24 h.
TARIC_CACHE_TTL_SECONDS = int(os.getenv("TARIC_CACHE_TTL_SECONDS", str(24 * 3600)))
TARIC_CACHE_MAX_SIZE = int(os.getenv("TARIC_CACHE_MAX_SIZE", "2048"))

# Proveedor secundario (sólo con credencial; útil cuando el flujo toca GB).
UK_TARIFF_API_URL = os.getenv(
    "UK_TARIFF_API_URL", "https://api.trade-tariff.service.gov.uk"
).rstrip("/")
UK_TARIFF_API_KEY = os.getenv("UK_TARIFF_API_KEY", "").strip()

# Interpretación LLM de las medidas (se degrada a respuesta estructurada sin resumen).
CUSTOMS_LLM_ENABLED = os.getenv("CUSTOMS_LLM_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on",
}

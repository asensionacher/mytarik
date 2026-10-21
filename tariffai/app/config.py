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

# --- LLM provider ---
# "gemini" (default legacy) o "minimax". Sobreescribible por request vía ClassifyRequest.provider.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "minimax").strip().lower()

# --- Gemini ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.8-flash")

# --- MiniMax (Anthropic-compatible) ---
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")
MINIMAX_DEFAULT_MODEL = os.getenv("MINIMAX_DEFAULT_MODEL", "MiniMax-M3.1-Flash")

# --- Retrieval ---
TOP_K_CANDIDATES = int(os.getenv("TOP_K_CANDIDATES", "10"))
SEMANTIC_WEIGHT = 0.6
BM25_WEIGHT = 0.4

# --- Classification ---
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))

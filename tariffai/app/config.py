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

# --- Deep reasoning (Stage 4) + human in the loop ---
# Below this confidence the pipeline reasons again over the HS catalogue.
REASONING_CONFIDENCE_THRESHOLD = float(os.getenv("REASONING_CONFIDENCE_THRESHOLD", "0.75"))
# Two candidates are considered tied when their relative margin is <= 0.1%.
TIE_MARGIN_THRESHOLD = float(os.getenv("TIE_MARGIN_THRESHOLD", "0.001"))
# A description shorter than this is too vague to classify without asking.
MIN_QUERY_CHARS = int(os.getenv("MIN_QUERY_CHARS", "25"))
MIN_QUERY_WORDS = int(os.getenv("MIN_QUERY_WORDS", "4"))
# Maximum clarifying questions the model may ask a human for a single line.
MAX_CLARIFYING_QUESTIONS = int(os.getenv("MAX_CLARIFYING_QUESTIONS", "3"))

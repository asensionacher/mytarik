from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    """Configuración del backend, leída del entorno."""

    tariffai_url: str = os.getenv("TARIFFAI_URL", "http://tariffai-api:8004").rstrip("/")
    log_level: str = os.getenv("LOG_LEVEL", "info").lower()
    request_timeout_seconds: float = float(os.getenv("TARIFFAI_TIMEOUT", "600"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))  # 20 MB
    tesseract_langs: str = os.getenv("TESSERACT_LANGS", "eng")


settings = Settings()

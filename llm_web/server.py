"""Local web chat with a selector for the installed models."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Modelos locales")

MODELS = [
    {
        "id": "qwen25-coder",
        "name": "Qwen2.5 Coder 32B",
        "description": "Código y agentes. 32K. 3 GPUs.",
        "base_url": "http://127.0.0.1:8085/v1",
        "model": "qwen2.5-coder-32b",
        "start": ["/home/seby/llama.cpp/start-qwen25-coder.sh"],
    },
    {
        "id": "laguna",
        "name": "Laguna S 2.1 Q4",
        "description": "118B MoE. 64K. Más lento.",
        "base_url": "http://127.0.0.1:8084/v1",
        "model": "laguna",
        "start": ["/home/seby/llama.cpp/start-laguna.sh"],
    },
    {
        "id": "strata-qwen-general",
        "name": "Qwen3.8 General (Strata)",
        "description": "Modelo general de Strata.",
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "qwen3.8-flash-next-unsloth-ud-iq4_xs",
        "start": ["/home/seby/.local/bin/strata", "launch", "--preset", "Qwen3.8 64K", "--yes", "--no-tui"],
    },
]


class ChatRequest(BaseModel):
    model_id: str
    messages: list[dict]
    temperature: float = 0.1
    max_tokens: int = 4096


def model_by_id(model_id: str) -> dict:
    for model in MODELS:
        if model["id"] == model_id:
            return model
    raise HTTPException(404, "Modelo no encontrado")


async def is_up(model: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{model['base_url']}/models")
            return response.status_code == 200
    except Exception:
        return False


@app.get("/")
async def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/models")
async def models():
    return JSONResponse([
        {
            "id": model["id"],
            "name": model["name"],
            "description": model["description"],
            "up": await is_up(model),
        }
        for model in MODELS
    ])


@app.post("/api/start/{model_id}")
async def start(model_id: str):
    model = model_by_id(model_id)
    if await is_up(model):
        return {"ok": True, "message": "Ya estaba arrancado"}
    try:
        subprocess.Popen(
            model["start"],
            cwd="/home/seby/mytarik",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        raise HTTPException(500, f"No se pudo arrancar: {exc}")
    for _ in range(90):
        if await is_up(model):
            return {"ok": True, "message": "Modelo arrancado"}
        await asyncio.sleep(2)
    raise HTTPException(504, "El modelo no respondió en 180 segundos")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    model = model_by_id(request.model_id)
    payload = {
        "model": model["model"],
        "messages": request.messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=900) as client:
            response = await client.post(f"{model['base_url']}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"El modelo devolvió {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(502, f"Error conectando con el modelo: {exc}")
    try:
        return {"content": data["choices"][0]["message"].get("content") or ""}
    except (KeyError, IndexError):
        raise HTTPException(502, "Respuesta inesperada del modelo")

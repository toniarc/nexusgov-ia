import logging

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get("/health", summary="Healthcheck (DB + Ollama)")
async def health(request: Request) -> JSONResponse:
    settings = get_settings()
    payload = {"db": "unknown", "llm": "unknown"}
    ok = True

    try:
        with request.app.state.db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        payload["db"] = "ok"
    except Exception as e:
        ok = False
        payload["db"] = f"erro: {type(e).__name__}"
        logger.exception("Healthcheck DB falhou")

    try:
        async with httpx.AsyncClient(timeout=5.0) as cli:
            resp = await cli.get(f"{settings.ollama_base_url.rstrip('/')}/api/version")
            payload["llm"] = "ok" if resp.status_code < 500 else f"http {resp.status_code}"
            if resp.status_code >= 500:
                ok = False
    except Exception as e:
        ok = False
        payload["llm"] = f"erro: {type(e).__name__}"

    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )

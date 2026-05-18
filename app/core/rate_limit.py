import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.config import get_settings

logger = logging.getLogger(__name__)


def _user_key(request: Request) -> str:
    """Chave de rate-limit: usuario_id se disponível, senão IP."""
    uid = getattr(request.state, "usuario_id", None)
    if uid is not None:
        return f"user:{uid}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


_settings = get_settings()
limiter = Limiter(key_func=_user_key, default_limits=[f"{_settings.rate_limit_per_minute}/minute"])


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    logger.warning("Rate limit excedido para %s", _user_key(request))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "status": 429,
            "erro": "Limite de requisições excedido",
            "mensagem": "Aguarde alguns instantes antes de tentar novamente.",
        },
    )

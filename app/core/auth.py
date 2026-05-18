import base64
import time
from threading import Lock

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.config import get_settings

_bearer = HTTPBearer(auto_error=True)

_CACHE_TTL_SECONDS = 300
_email_cache: dict[str, tuple[int, float]] = {}
_cache_lock = Lock()


def _resolve_usuario_id(email: str, request: Request) -> int:
    now = time.monotonic()
    with _cache_lock:
        hit = _email_cache.get(email)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]

    engine = request.app.state.db_engine
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM nexusgov.usuario WHERE email = :email AND ativo = true"),
            {"email": email},
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado ou inativo",
        )

    with _cache_lock:
        _email_cache[email] = (row[0], now)
        if len(_email_cache) > 1024:
            oldest = min(_email_cache.items(), key=lambda kv: kv[1][1])[0]
            _email_cache.pop(oldest, None)

    return row[0]


def invalidar_cache_usuario(email: str | None = None) -> None:
    with _cache_lock:
        if email is None:
            _email_cache.clear()
        else:
            _email_cache.pop(email, None)


def get_usuario_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """
    Valida JWT do nexusgov-api, extrai email do claim 'sub' e resolve usuario.id.
    Cache em memória (5min TTL) reduz round-trips ao banco.
    """
    settings = get_settings()
    token = credentials.credentials

    try:
        secret_bytes = base64.b64decode(settings.jwt_secret)
        payload = jwt.decode(token, secret_bytes, algorithms=settings.jwt_algorithms_list)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    email: str | None = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sem identificador de usuário",
        )

    return _resolve_usuario_id(email, request)

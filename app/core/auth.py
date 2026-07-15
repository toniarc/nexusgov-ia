import time
from functools import lru_cache
from threading import Lock

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import text

from app.config import get_settings

_bearer = HTTPBearer(auto_error=True)

_CACHE_TTL_SECONDS = 300
_usuario_cache: dict[str, tuple[int, float]] = {}
_cache_lock = Lock()


@lru_cache()
def _jwk_client() -> PyJWKClient:
    """Cliente JWKS do realm. As chaves públicas são cacheadas pelo próprio cliente,
    e recarregadas quando o Keycloak rotaciona a chave (kid desconhecido)."""
    return PyJWKClient(get_settings().keycloak_jwks_uri)


def _resolve_usuario_id(keycloak_id: str, request: Request) -> int:
    now = time.monotonic()
    with _cache_lock:
        hit = _usuario_cache.get(keycloak_id)
        if hit and now - hit[1] < _CACHE_TTL_SECONDS:
            return hit[0]

    engine = request.app.state.db_engine
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM nexusgov.usuario "
                "WHERE keycloak_id = CAST(:keycloak_id AS uuid) AND ativo = true"
            ),
            {"keycloak_id": keycloak_id},
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado ou inativo",
        )

    with _cache_lock:
        _usuario_cache[keycloak_id] = (row[0], now)
        if len(_usuario_cache) > 1024:
            oldest = min(_usuario_cache.items(), key=lambda kv: kv[1][1])[0]
            _usuario_cache.pop(oldest, None)

    return row[0]


def invalidar_cache_usuario(keycloak_id: str | None = None) -> None:
    with _cache_lock:
        if keycloak_id is None:
            _usuario_cache.clear()
        else:
            _usuario_cache.pop(keycloak_id, None)


def get_usuario_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """
    Valida o JWT emitido pelo Keycloak (assinatura RS256 conferida contra o JWKS do
    realm) e resolve usuario.id pelo claim 'sub', que casa com usuario.keycloak_id.

    A audience não é verificada, espelhando o nexusgov-api (Spring Resource Server
    configurado só com issuer-uri). Cache em memória (5min TTL) reduz round-trips ao banco.
    """
    settings = get_settings()
    token = credentials.credentials

    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível validar o token: Keycloak inacessível",
        )
    except (jwt.PyJWKClientError, jwt.InvalidTokenError):
        # get_signing_key_from_jwt decodifica o header/payload sem verificar assinatura:
        # token malformado levanta InvalidTokenError aqui, antes do jwt.decode abaixo.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.jwt_algorithms_list,
            issuer=settings.keycloak_issuer_uri,
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    keycloak_id: str | None = payload.get("sub")
    if not keycloak_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sem identificador de usuário",
        )

    return _resolve_usuario_id(keycloak_id, request)

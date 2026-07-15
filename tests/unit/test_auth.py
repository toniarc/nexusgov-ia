"""Validação de tokens do Keycloak: assinatura RS256 via JWKS e resolução por keycloak_id."""

from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.core import auth

_ISSUER = "http://keycloak.test/realms/nexusgov"
_SUB = "88db5b23-1568-4a1e-b7a1-f3313d2ee48b"


@pytest.fixture(scope="module")
def chave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def outra_chave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(chave_privada, alg="RS256", **overrides) -> str:
    import time

    claims = {
        "sub": _SUB,
        "iss": _ISSUER,
        "aud": "account",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "email": "administrador@teste.com",
    }
    claims.update(overrides)
    return jwt.encode(claims, chave_privada, algorithm=alg)


class _FakeRow(tuple):
    pass


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def execute(self, *a, **k):
        return SimpleNamespace(fetchone=lambda: self._row)

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False


class _FakeEngine:
    def __init__(self, row):
        self._row = row

    def connect(self):
        return _FakeConn(self._row)


def _request(row=(13,)):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_engine=_FakeEngine(row))))


def _credentials(token):
    return SimpleNamespace(credentials=token)


@pytest.fixture(autouse=True)
def _ambiente(chave, monkeypatch):
    """Aponta o issuer para o realm de teste e serve a chave pública no lugar do JWKS."""
    settings = auth.get_settings()
    monkeypatch.setattr(settings, "keycloak_issuer_uri", _ISSUER, raising=False)
    monkeypatch.setattr(settings, "jwt_algorithms", "RS256", raising=False)
    auth.invalidar_cache_usuario()
    yield
    auth.invalidar_cache_usuario()


def _com_jwks(chave_publica):
    """Substitui o cliente JWKS pela chave pública informada."""
    return patch.object(
        auth,
        "_jwk_client",
        return_value=SimpleNamespace(
            get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=chave_publica)
        ),
    )


def test_token_valido_resolve_usuario_por_keycloak_id(chave):
    with _com_jwks(chave.public_key()):
        assert auth.get_usuario_id(_request(row=(13,)), _credentials(_token(chave))) == 13


def test_token_assinado_por_outra_chave_e_rejeitado(chave, outra_chave):
    """Token forjado com chave que não é a do realm não pode passar."""
    with _com_jwks(chave.public_key()):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(_request(), _credentials(_token(outra_chave)))
    assert e.value.status_code == 401
    assert e.value.detail == "Token inválido"


def test_token_expirado(chave):
    import time

    with _com_jwks(chave.public_key()):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(
                _request(),
                _credentials(_token(chave, exp=int(time.time()) - 10, iat=int(time.time()) - 320)),
            )
    assert e.value.status_code == 401
    assert e.value.detail == "Token expirado"


def test_issuer_diferente_e_rejeitado(chave):
    with _com_jwks(chave.public_key()):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(
                _request(), _credentials(_token(chave, iss="http://malicioso/realms/x"))
            )
    assert e.value.status_code == 401


def test_audience_nao_e_exigida(chave):
    """Espelha o nexusgov-api: aud não é validada, qualquer valor passa."""
    with _com_jwks(chave.public_key()):
        assert auth.get_usuario_id(_request(row=(13,)), _credentials(_token(chave, aud="outro"))) == 13


def test_usuario_inexistente_ou_inativo(chave):
    with _com_jwks(chave.public_key()):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(_request(row=None), _credentials(_token(chave)))
    assert e.value.status_code == 401
    assert "não encontrado" in e.value.detail


def test_token_sem_sub(chave):
    with _com_jwks(chave.public_key()):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(_request(), _credentials(_token(chave, sub="")))
    assert e.value.status_code == 401
    assert "sem identificador" in e.value.detail


@pytest.mark.parametrize(
    "token_ruim",
    ["nao-e-um-jwt", "a.b.c", "", "eyJhbGciOiJSUzI1NiJ9.payload-invalido.assinatura"],
    ids=["sem_pontos", "base64_invalido", "vazio", "payload_nao_json"],
)
def test_token_malformado_vira_401_e_nao_500(chave, token_ruim):
    """get_signing_key_from_jwt decodifica o token antes de conferir a assinatura:
    se a exceção escapar, o cliente recebe 500 em vez de 401."""
    with _com_jwks(chave.public_key()):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(_request(), _credentials(token_ruim))
    assert e.value.status_code == 401


def test_keycloak_inacessivel_retorna_503(chave):
    def _explode(_t):
        raise jwt.PyJWKClientConnectionError("sem rede")

    with patch.object(
        auth, "_jwk_client", return_value=SimpleNamespace(get_signing_key_from_jwt=_explode)
    ):
        with pytest.raises(HTTPException) as e:
            auth.get_usuario_id(_request(), _credentials(_token(chave)))
    assert e.value.status_code == 503, "falha de infra não deve virar 401"


def test_cache_evita_segunda_consulta_ao_banco(chave):
    engine_row = (13,)
    consultas = []

    class _ContandoEngine(_FakeEngine):
        def connect(self):
            consultas.append(1)
            return _FakeConn(engine_row)

    req = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_engine=_ContandoEngine(engine_row)))
    )
    with _com_jwks(chave.public_key()):
        auth.get_usuario_id(req, _credentials(_token(chave)))
        auth.get_usuario_id(req, _credentials(_token(chave)))

    assert len(consultas) == 1, "segunda chamada deve vir do cache"

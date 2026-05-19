import pytest
import requests
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(integration_enabled):
    if not integration_enabled:
        pytest.skip("RUN_INTEGRATION_TESTS!=1; pulando integration tests")
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="module")
def token(integration_enabled, nexusgov_api_url):
    if not integration_enabled:
        pytest.skip("integration disabled")
    resp = requests.post(
        f"{nexusgov_api_url}/api/v1/auth/login",
        json={"email": "fiscal@teste.com", "senha": "senha123"},
        timeout=10,
    )
    assert resp.status_code == 200
    return resp.json().get("accessToken") or resp.json().get("token")


def test_health(client):
    r = client.get("/health")
    assert r.status_code in (200, 503)
    assert "db" in r.json() and "llm" in r.json()


def test_chat_sem_token_401(client):
    r = client.post("/api/v1/chat", json={"mensagem": "oi"})
    assert r.status_code in (401, 403)


def test_chat_aguardando_contrato(client, token):
    import json

    r = client.post(
        "/api/v1/chat",
        json={"mensagem": "olá"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    eventos: list[dict] = []
    for raw in r.text.split("\n"):
        if raw.startswith("data:"):
            eventos.append(json.loads(raw.split(":", 1)[1].strip()))

    assert eventos, "stream vazio"
    assert any(ev["type"] == "delta" for ev in eventos)
    assert eventos[-1]["type"] == "done"

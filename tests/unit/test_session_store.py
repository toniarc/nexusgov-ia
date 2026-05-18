import time
from datetime import timedelta

from app.services.session_store import InMemorySessionStore, SessionState


def test_get_or_create_retorna_mesma_sessao():
    store = InMemorySessionStore(max_size=10, ttl_minutes=60)
    s1 = store.get_or_create(1)
    s2 = store.get_or_create(1)
    assert s1 is s2


def test_lru_evicta_mais_antigo():
    store = InMemorySessionStore(max_size=2, ttl_minutes=60)
    store.get_or_create(1)
    store.get_or_create(2)
    store.get_or_create(3)
    assert 1 not in store._store
    assert 2 in store._store and 3 in store._store


def test_ttl_evicta_expirado():
    store = InMemorySessionStore(max_size=10, ttl_minutes=60)
    s = store.get_or_create(1)
    s.ultima_atividade = s.ultima_atividade - timedelta(hours=2)
    store.get_or_create(2)
    assert 1 not in store._store


def test_adicionar_mensagem_trunca_em_20():
    state = SessionState(usuario_id=1)
    for i in range(30):
        state.adicionar_mensagem("user", f"msg{i}")
    assert len(state.historico) == 20
    assert state.historico[0]["content"] == "msg10"


def test_serializacao_roundtrip():
    state = SessionState(usuario_id=42, contrato_id=10, contrato_ano=2024, contrato_numero=1)
    state.adicionar_mensagem("user", "hello")
    d = state.to_dict()
    restored = SessionState.from_dict(d)
    assert restored.usuario_id == 42
    assert restored.contrato_id == 10
    assert restored.historico == state.historico

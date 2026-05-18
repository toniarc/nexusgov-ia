import json
import logging
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    usuario_id: int
    contrato_id: int | None = None
    contrato_ano: int | None = None
    contrato_numero: int | None = None
    historico: list[dict] = field(default_factory=list)
    resumo_historico: str = ""
    ultima_atividade: datetime = field(default_factory=datetime.utcnow)

    def atualizar_contrato(self, contrato_id: int, ano: int, numero: int) -> None:
        self.contrato_id = contrato_id
        self.contrato_ano = ano
        self.contrato_numero = numero

    def adicionar_mensagem(self, role: str, content: str) -> None:
        self.historico.append({"role": role, "content": content})
        if len(self.historico) > 20:
            self.historico = self.historico[-20:]

    def historico_recente(self, n: int = 6) -> list[dict]:
        return self.historico[-n:]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ultima_atividade"] = self.ultima_atividade.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        d = dict(d)
        ts = d.get("ultima_atividade")
        if isinstance(ts, str):
            d["ultima_atividade"] = datetime.fromisoformat(ts)
        return cls(**d)


class SessionStore(Protocol):
    def get_or_create(self, usuario_id: int) -> SessionState: ...
    def update(self, state: SessionState) -> None: ...


class InMemorySessionStore:
    """Sessões em memória com TTL e LRU eviction. Apenas para dev / single-instance."""

    def __init__(self, max_size: int, ttl_minutes: int):
        self._max_size = max_size
        self._ttl = timedelta(minutes=ttl_minutes)
        self._store: OrderedDict[int, SessionState] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_create(self, usuario_id: int) -> SessionState:
        with self._lock:
            self._evict_expired()
            if usuario_id in self._store:
                self._store.move_to_end(usuario_id)
                return self._store[usuario_id]
            state = SessionState(usuario_id=usuario_id)
            self._store[usuario_id] = state
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)
            return state

    def update(self, state: SessionState) -> None:
        with self._lock:
            state.ultima_atividade = datetime.utcnow()
            self._store[state.usuario_id] = state
            self._store.move_to_end(state.usuario_id)

    def _evict_expired(self) -> None:
        agora = datetime.utcnow()
        expirados = [uid for uid, s in self._store.items() if agora - s.ultima_atividade > self._ttl]
        for uid in expirados:
            del self._store[uid]


class RedisSessionStore:
    """Persistência de sessão em Redis com TTL nativo."""

    def __init__(self, redis_url: str, ttl_minutes: int):
        import redis  # import tardio: dependência opcional

        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl_seconds = ttl_minutes * 60
        self._redis.ping()
        logger.info("RedisSessionStore conectado em %s", redis_url)

    def _key(self, usuario_id: int) -> str:
        return f"nexusgov-ia:session:{usuario_id}"

    def get_or_create(self, usuario_id: int) -> SessionState:
        raw = self._redis.get(self._key(usuario_id))
        if raw:
            try:
                return SessionState.from_dict(json.loads(raw))
            except Exception:
                logger.exception("Sessão corrompida em Redis para usuario_id=%s; recriando", usuario_id)
        return SessionState(usuario_id=usuario_id)

    def update(self, state: SessionState) -> None:
        state.ultima_atividade = datetime.utcnow()
        self._redis.setex(self._key(state.usuario_id), self._ttl_seconds, json.dumps(state.to_dict()))

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception:
            logger.exception("Erro ao fechar Redis")


def build_session_store() -> SessionStore:
    settings = get_settings()
    if settings.session_backend.lower() == "redis":
        return RedisSessionStore(settings.redis_url, settings.session_ttl_minutes)
    return InMemorySessionStore(settings.session_max_size, settings.session_ttl_minutes)

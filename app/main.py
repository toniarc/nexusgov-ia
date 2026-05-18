import logging
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.chat import router as chat_router
from app.api.v1.health import router as health_router
from app.config import get_settings
from app.core.exceptions import registrar_handlers
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.services.database import attach_sql_logger, create_engine_db
from app.services.query_engine import (
    build_sql_database,
    build_table_object_index,
    configure_llama_globals,
)
from app.services.session_store import build_session_store
from slowapi.errors import RateLimitExceeded


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
)
for h in logging.getLogger().handlers:
    h.addFilter(RequestIdFilter())

logger = logging.getLogger(__name__)
_settings = get_settings()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if _settings.sql_echo else logging.WARNING)


class RequestIdMiddleware:
    """ASGI middleware puro — não buferiza StreamingResponse."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        rid = headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", rid.encode("latin-1")))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando nexusgov-ia...")
    configure_llama_globals()
    app.state.db_engine = create_engine_db()
    app.state.sql_database = build_sql_database(app.state.db_engine)
    app.state.table_object_index = build_table_object_index(app.state.sql_database)
    attach_sql_logger(app.state.db_engine)
    app.state.session_store = build_session_store()
    logger.info("nexusgov-ia pronto.")
    yield
    logger.info("Encerrando nexusgov-ia...")
    app.state.db_engine.dispose()
    close = getattr(app.state.session_store, "close", None)
    if callable(close):
        close()


def criar_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NexusGov IA",
        description="Chat inteligente sobre contratos governamentais — NexusGov",
        version="1.0.0",
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        allow_credentials=False,
    )

    registrar_handlers(app)
    app.include_router(health_router)
    app.include_router(chat_router)

    return app


app = criar_app()

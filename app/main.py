import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.v1.chat import router as chat_router
from app.api.v1.documentos import router as documentos_router
from app.api.v1.health import router as health_router
from app.config import get_settings
from app.core.exceptions import registrar_handlers
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.request_id import RequestIdMiddleware, configurar_logging
from app.services.database import attach_sql_logger, create_engine_db
from app.services.ingest_service import encerrar_poller, iniciar_poller
from app.services.query_engine import (
    build_sql_database,
    build_table_object_index,
    configure_llama_globals,
)
from app.services.session_store import build_session_store

configurar_logging(sql_echo=get_settings().sql_echo)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando nexusgov-ia...")
    configure_llama_globals()
    app.state.db_engine = create_engine_db()
    app.state.sql_database = build_sql_database(app.state.db_engine)
    app.state.table_object_index = build_table_object_index(app.state.sql_database)
    attach_sql_logger(app.state.db_engine)
    app.state.session_store = build_session_store()
    iniciar_poller(app)
    logger.info("nexusgov-ia pronto.")
    yield
    logger.info("Encerrando nexusgov-ia...")
    await encerrar_poller(app)
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
    app.include_router(documentos_router)

    return app


app = criar_app()

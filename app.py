#!/usr/bin/env python3
"""Script para iniciar a API REST usando Clean Architecture."""

import logging
import uvicorn
import warnings
from app.config import get_settings

# Suprimir warnings de Pydantic v2 de bibliotecas antigas
warnings.filterwarnings("ignore", message="Valid config keys have changed in V2")

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    """Inicia o servidor FastAPI. Use APP_RELOAD=true apenas em desenvolvimento local."""
    settings = get_settings()
    if settings.app_reload:
        logger.warning("APP_RELOAD=true: ative apenas em desenvolvimento local.")
    
    # Configurações do servidor
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
        log_level="info",
        access_log=True,
        timeout_keep_alive=300,  # 5 minutos para conexões keep-alive
        timeout_graceful_shutdown=30,  # 30 segundos para shutdown gracioso
    )


if __name__ == "__main__":
    main()
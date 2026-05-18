import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

logger = logging.getLogger(__name__)


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(OperationalError)
    async def banco_indisponivel(request: Request, exc: OperationalError):
        logger.exception("OperationalError em %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": 503,
                "erro": "Banco indisponível",
                "mensagem": "Tente novamente em instantes.",
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def erro_sql(request: Request, exc: SQLAlchemyError):
        logger.exception("SQLAlchemyError em %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": 500,
                "erro": "Erro de banco",
                "mensagem": "Não foi possível concluir a consulta.",
            },
        )

    @app.exception_handler(Exception)
    async def erro_generico(request: Request, exc: Exception):
        logger.exception("Exceção não tratada em %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": 500,
                "erro": "Erro interno",
                "mensagem": "Ocorreu um erro inesperado. Tente novamente.",
            },
        )

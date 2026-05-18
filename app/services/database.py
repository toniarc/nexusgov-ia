import logging

import sqlparse
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from app.config import get_settings

logger = logging.getLogger("nexusgov.sql")


def _log_query(conn, cursor, statement, parameters, context, executemany):
    try:
        formatted = sqlparse.format(
            statement,
            reindent=True,
            keyword_case="upper",
            strip_comments=False,
        )
    except Exception:
        formatted = statement
    header = "─" * 80
    params_repr = repr(parameters) if parameters else "(sem parâmetros)"
    logger.info(
        "\n%s\n[SQL]%s\n%s\n[PARAMS] %s\n%s",
        header,
        " (executemany)" if executemany else "",
        formatted,
        params_repr,
        header,
    )


def create_engine_db() -> Engine:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        connect_args={"options": "-c search_path=nexusgov,public"},
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.sql_echo,
    )
    return engine


def attach_sql_logger(engine: Engine) -> None:
    event.listen(engine, "before_cursor_execute", _log_query)

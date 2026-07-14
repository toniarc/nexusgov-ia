"""Request-ID: contextvar, filtro de logging e middleware ASGI puro."""

import logging
import uuid
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


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


def configurar_logging(sql_echo: bool) -> None:
    """Logging global com request_id no formato. Chamado uma vez no import do main."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
    )
    for h in logging.getLogger().handlers:
        h.addFilter(RequestIdFilter())
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if sql_echo else logging.WARNING
    )

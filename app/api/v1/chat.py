import json

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.core.auth import get_usuario_id
from app.core.rate_limit import limiter
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/v1", tags=["Chat IA"])


def _get_chat_service(request: Request) -> ChatService:
    return ChatService(
        sql_database=request.app.state.sql_database,
        table_object_index=request.app.state.table_object_index,
        session_store=request.app.state.session_store,
    )


@router.post(
    "/chat",
    status_code=status.HTTP_200_OK,
    summary="Chat sobre contrato (SSE streaming, com thinking)",
    response_class=StreamingResponse,
)
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
async def chat(
    request: Request,
    payload: ChatRequest,
    usuario_id: int = Depends(get_usuario_id),
    chat_service: ChatService = Depends(_get_chat_service),
) -> StreamingResponse:
    request.state.usuario_id = usuario_id

    async def event_gen():
        async for ev in chat_service.processar_mensagem_stream(usuario_id, payload.mensagem):
            data = json.dumps(ev.data, ensure_ascii=False)
            yield f"event: {ev.event}\ndata: {data}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

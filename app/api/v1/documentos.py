"""Endpoints de acompanhamento da ingestão de documentos de contrato.

Perguntas sobre o conteúdo dos documentos usam o chat existente
(`POST /api/v1/chat`) — a tool `documentos_contrato` faz a busca semântica.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.auth import get_usuario_id
from app.schemas.documentos import (
    IngestaoAnexoStatus,
    IngestaoContratoResponse,
    ReprocessarResponse,
)
from app.services.ingest_service import (
    processar_pendentes,
    reprocessar_contrato,
    status_ingestao_contrato,
)

router = APIRouter(prefix="/api/v1/contratos/{contrato_id}/documentos", tags=["Documentos IA"])

# Referências fortes a tasks fire-and-forget (evita GC antes de concluir).
_background_tasks: set[asyncio.Task] = set()


@router.get(
    "/ingestao",
    status_code=status.HTTP_200_OK,
    summary="Status da ingestão dos anexos do contrato",
    response_model=IngestaoContratoResponse,
)
async def status_ingestao(
    request: Request,
    contrato_id: int,
    usuario_id: int = Depends(get_usuario_id),
) -> IngestaoContratoResponse:
    engine = request.app.state.db_engine
    anexos = await asyncio.to_thread(status_ingestao_contrato, engine, contrato_id)
    return IngestaoContratoResponse(
        contrato_id=contrato_id,
        anexos=[
            IngestaoAnexoStatus(
                anexo_id=a["id"],
                nome_arquivo=a["nome_arquivo"],
                tipo=a["tipo"],
                descricao=a["descricao"],
                status=a["status"],
                num_chunks=a["num_chunks"],
                erro=a["erro"],
                tentativas=a["tentativas"],
                alterado_em=a["alterado_em"],
            )
            for a in anexos
        ],
    )


@router.post(
    "/ingestao",
    status_code=status.HTTP_200_OK,
    summary="Força reingestão dos anexos do contrato",
    response_model=ReprocessarResponse,
)
async def forcar_reingestao(
    request: Request,
    contrato_id: int,
    usuario_id: int = Depends(get_usuario_id),
) -> ReprocessarResponse:
    engine = request.app.state.db_engine
    afetados = await asyncio.to_thread(reprocessar_contrato, engine, contrato_id)
    if afetados == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum anexo com arquivo encontrado para o contrato {contrato_id}",
        )
    # Dispara um ciclo imediato em background (poller também pegaria no próximo intervalo).
    task = asyncio.create_task(asyncio.to_thread(processar_pendentes, engine))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return ReprocessarResponse(
        contrato_id=contrato_id,
        reprocessando=afetados,
        mensagem="Reingestão agendada. Acompanhe pelo GET /ingestao.",
    )

"""Ingestão de anexos de contrato: MinIO → texto (OCR se preciso) → chunks → bge-m3 → pgvector.

Poller roda em background (lifespan) e varre `contrato_anexo` sem ingestão concluída.
Estado por anexo nas colunas `ingestao_*` de `contrato_anexo`; chunks em
`contrato_documento_chunk`.
"""

import asyncio
import logging

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.services.document_extractor import extrair_texto
from app.services.embedding_service import (
    dividir_em_chunks,
    gerar_embeddings_em_lotes,
    vetor_para_literal,
)
from app.services.storage import baixar_anexo

logger = logging.getLogger(__name__)

# Anexos pendentes, com erro (dentro do limite de tentativas) ou presos em
# PROCESSANDO sem progresso (instância anterior morreu no meio).
#
# `ingestao_em` recebe heartbeat a cada lote de embeddings durante o processamento,
# então a comparação abaixo mede tempo SEM PROGRESSO, não tempo desde o claim. Sem
# o heartbeat, documentos que demoram mais que o limite seriam re-claimados enquanto
# ainda estavam sendo processados.
_SQL_PENDENTES = text(
    """
    SELECT a.id, a.contrato_id, a.nome_arquivo, a.arquivo_key
      FROM nexusgov.contrato_anexo a
     WHERE a.arquivo_key IS NOT NULL
       AND (
            a.ingestao_status = 'PENDENTE'
            OR (a.ingestao_status = 'ERRO' AND a.ingestao_tentativas < :max_tentativas)
            OR (a.ingestao_status = 'PROCESSANDO'
                AND a.ingestao_em < now() - make_interval(mins => :travado_minutos))
       )
     ORDER BY a.id
     LIMIT :lote
    """
)

# Marca progresso do anexo em processamento (ver comentário em _SQL_PENDENTES).
_SQL_HEARTBEAT = text(
    "UPDATE nexusgov.contrato_anexo SET ingestao_em = now() WHERE id = :anexo_id"
)

_SQL_CLAIM = text(
    """
    UPDATE nexusgov.contrato_anexo
       SET ingestao_status = 'PROCESSANDO', ingestao_em = now()
     WHERE id = :anexo_id
    """
)

_SQL_SUCESSO = text(
    """
    UPDATE nexusgov.contrato_anexo
       SET ingestao_status = 'CONCLUIDO', ingestao_num_chunks = :num_chunks,
           ingestao_erro = NULL, ingestao_em = now()
     WHERE id = :anexo_id
    """
)

_SQL_ERRO = text(
    """
    UPDATE nexusgov.contrato_anexo
       SET ingestao_status = 'ERRO', ingestao_erro = :erro,
           ingestao_tentativas = ingestao_tentativas + 1, ingestao_em = now()
     WHERE id = :anexo_id
    """
)

_SQL_LIMPAR_CHUNKS = text(
    "DELETE FROM nexusgov.contrato_documento_chunk WHERE contrato_anexo_id = :anexo_id"
)

_SQL_INSERIR_CHUNK = text(
    """
    INSERT INTO nexusgov.contrato_documento_chunk
        (contrato_id, contrato_anexo_id, nome_arquivo, chunk_index, conteudo, embedding)
    VALUES (:contrato_id, :anexo_id, :nome_arquivo, :chunk_index, :conteudo, (:embedding)::vector)
    """
)

_SQL_STATUS_CONTRATO = text(
    """
    SELECT a.id, a.nome_arquivo, a.tipo, a.descricao,
           a.ingestao_status AS status,
           a.ingestao_num_chunks AS num_chunks,
           a.ingestao_erro AS erro,
           a.ingestao_tentativas AS tentativas,
           a.ingestao_em AS alterado_em
      FROM nexusgov.contrato_anexo a
     WHERE a.contrato_id = :contrato_id
     ORDER BY a.id DESC
    """
)

_SQL_REPROCESSAR_CONTRATO = text(
    """
    UPDATE nexusgov.contrato_anexo
       SET ingestao_status = 'PENDENTE', ingestao_tentativas = 0,
           ingestao_erro = NULL, ingestao_em = now()
     WHERE contrato_id = :contrato_id
       AND arquivo_key IS NOT NULL
    """
)


def processar_pendentes(engine: Engine) -> int:
    """Processa um lote de anexos pendentes. Retorna quantidade processada com sucesso."""
    settings = get_settings()
    with engine.connect() as conn:
        pendentes = conn.execute(
            _SQL_PENDENTES,
            {
                "max_tentativas": settings.ingest_max_tentativas,
                "lote": settings.ingest_lote,
                "travado_minutos": settings.ingest_travado_minutos,
            },
        ).fetchall()

    sucesso = 0
    for anexo_id, contrato_id, nome_arquivo, arquivo_key in pendentes:
        with engine.begin() as conn:
            conn.execute(_SQL_CLAIM, {"anexo_id": anexo_id})
        try:
            num_chunks = _ingerir_anexo(engine, anexo_id, contrato_id, nome_arquivo, arquivo_key)
            with engine.begin() as conn:
                conn.execute(_SQL_SUCESSO, {"anexo_id": anexo_id, "num_chunks": num_chunks})
            logger.info(
                "Ingestão concluída: anexo=%s contrato=%s arquivo=%r chunks=%s",
                anexo_id, contrato_id, nome_arquivo, num_chunks,
            )
            sucesso += 1
        except Exception as e:
            logger.exception("Falha na ingestão do anexo %s (%r)", anexo_id, nome_arquivo)
            with engine.begin() as conn:
                conn.execute(_SQL_ERRO, {"anexo_id": anexo_id, "erro": f"{type(e).__name__}: {e}"[:2000]})
    return sucesso


def _ingerir_anexo(
    engine: Engine, anexo_id: int, contrato_id: int, nome_arquivo: str | None, arquivo_key: str
) -> int:
    settings = get_settings()

    conteudo = baixar_anexo(arquivo_key)
    texto_doc = extrair_texto(conteudo, nome_arquivo)
    chunks = dividir_em_chunks(texto_doc, settings.chunk_max_chars, settings.chunk_min_chars)
    if not chunks:
        raise RuntimeError("Nenhum texto extraído do documento")

    # Descarta chunks de uma execução anterior antes de repovoar: o anexo pode estar
    # sendo reprocessado após erro/interrupção.
    with engine.begin() as conn:
        conn.execute(_SQL_LIMPAR_CHUNKS, {"anexo_id": anexo_id})

    logger.info(
        "Ingerindo anexo=%s arquivo=%r: %s chunks", anexo_id, nome_arquivo, len(chunks)
    )
    gravados = 0
    for offset, lote, embeddings in gerar_embeddings_em_lotes(chunks):
        gravar_chunks(engine, anexo_id, contrato_id, nome_arquivo, offset, lote, embeddings)
        gravados += len(lote)

    return gravados


def gravar_chunks(
    engine: Engine,
    anexo_id: int,
    contrato_id: int,
    nome_arquivo: str | None,
    offset: int,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    """Grava um lote de chunks e marca progresso do anexo, na mesma transação.

    O heartbeat vai junto com os inserts para que `ingestao_em` só avance quando há
    progresso real gravado.
    """
    with engine.begin() as conn:
        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings), start=offset):
            conn.execute(
                _SQL_INSERIR_CHUNK,
                {
                    "contrato_id": contrato_id,
                    "anexo_id": anexo_id,
                    "nome_arquivo": nome_arquivo,
                    "chunk_index": idx,
                    "conteudo": chunk,
                    "embedding": vetor_para_literal(emb),
                },
            )
        conn.execute(_SQL_HEARTBEAT, {"anexo_id": anexo_id})


def status_ingestao_contrato(engine: Engine, contrato_id: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(_SQL_STATUS_CONTRATO, {"contrato_id": contrato_id}).mappings().all()
    return [dict(r) for r in rows]


def reprocessar_contrato(engine: Engine, contrato_id: int) -> int:
    """Marca anexos do contrato como PENDENTE (poller reprocessa). Retorna linhas afetadas."""
    with engine.begin() as conn:
        result = conn.execute(_SQL_REPROCESSAR_CONTRATO, {"contrato_id": contrato_id})
    return result.rowcount or 0


async def _ingest_loop(engine: Engine) -> None:
    settings = get_settings()
    logger.info(
        "Poller de ingestão iniciado (intervalo=%ss, modelo=%s)",
        settings.ingest_poll_seconds, settings.ollama_embed_model,
    )
    while True:
        try:
            await asyncio.to_thread(processar_pendentes, engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro no ciclo do poller de ingestão")
        await asyncio.sleep(settings.ingest_poll_seconds)


def iniciar_poller(app: FastAPI) -> None:
    """Inicia o poller de ingestão em background, se habilitado (chamado no lifespan)."""
    app.state.ingest_task = None
    if get_settings().ingest_enabled:
        app.state.ingest_task = asyncio.get_running_loop().create_task(
            _ingest_loop(app.state.db_engine)
        )


async def encerrar_poller(app: FastAPI) -> None:
    """Cancela o poller de ingestão e aguarda finalizar (chamado no shutdown)."""
    task = getattr(app.state, "ingest_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

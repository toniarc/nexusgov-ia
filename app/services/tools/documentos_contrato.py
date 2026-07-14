"""Tool de busca semântica nos documentos (anexos) do contrato ativo.

Embeda a pergunta com bge-m3 (Ollama local) e recupera os chunks mais
relevantes de `contrato_documento_chunk` (pgvector, distância de cosseno).
O resultado alimenta o synthesis prompt do chat, como as demais tools.
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.services.embedding_service import gerar_embeddings, vetor_para_literal
from app.services.tools.base import ToolSpec


class _Args(BaseModel):
    pergunta: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Pergunta do usuário, na íntegra, para busca semântica nos documentos",
    )


_SQL_BUSCAR_CHUNKS = text(
    """
    SELECT c.conteudo, c.nome_arquivo,
           1 - (c.embedding <=> (:embedding)::vector) AS similaridade
      FROM nexusgov.contrato_documento_chunk c
     WHERE c.contrato_id = :contrato_id
     ORDER BY c.embedding <=> (:embedding)::vector
     LIMIT :top_k
    """
)


def buscar_chunks_relevantes(engine: Engine, contrato_id: int, pergunta: str) -> list[dict]:
    """Busca por similaridade os chunks do contrato mais próximos da pergunta."""
    settings = get_settings()
    embedding = gerar_embeddings([pergunta])[0]
    with engine.connect() as conn:
        rows = conn.execute(
            _SQL_BUSCAR_CHUNKS,
            {
                "contrato_id": contrato_id,
                "embedding": vetor_para_literal(embedding),
                "top_k": settings.doc_chat_top_k,
            },
        ).mappings().all()
    return [dict(r) for r in rows]


def _handler(engine: Engine, contrato_id: int, pergunta: str) -> dict[str, Any]:
    chunks = buscar_chunks_relevantes(engine, contrato_id, pergunta)
    if not chunks:
        return {
            "encontrado": False,
            "aviso": (
                "Não há documentos ingeridos para este contrato. "
                "Anexe documentos ao contrato e aguarde a ingestão."
            ),
        }
    return {
        "encontrado": True,
        "instrucao": (
            "Responda usando EXCLUSIVAMENTE os trechos abaixo, extraídos dos documentos "
            "anexados ao contrato. Se a informação não estiver nos trechos, diga que não a "
            "encontrou nos documentos — não invente. Cite o arquivo de origem quando relevante."
        ),
        "fontes": sorted({c["nome_arquivo"] for c in chunks if c["nome_arquivo"]}),
        "trechos": [
            {
                "arquivo": c["nome_arquivo"],
                "similaridade": round(float(c["similaridade"]), 4),
                "texto": c["conteudo"],
            }
            for c in chunks
        ],
    }


SPEC = ToolSpec(
    name="documentos_contrato",
    description=(
        "Busca semântica no CONTEÚDO dos documentos/anexos do contrato ativo (PDF do contrato, "
        "termo de referência, edital, aditivos, planilhas digitalizadas etc.). Use quando a "
        "pergunta se referir a cláusulas, objeto, garantias, multas, penalidades, prazos, "
        "condições de pagamento, especificações técnicas ou qualquer texto que esteja escrito "
        "nos documentos anexados — e não em dados estruturados do sistema (postos, atestos, "
        "valores cadastrados). Recebe a pergunta do usuário na íntegra."
    ),
    args_model=_Args,
    handler=_handler,
)

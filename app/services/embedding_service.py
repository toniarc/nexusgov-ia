"""Embeddings de documentos via Ollama local (modelo bge-m3, pgvector)."""

import logging
import re
from collections.abc import Iterator

from ollama import Client

from app.config import get_settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 16


def get_embed_client() -> Client:
    settings = get_settings()
    headers = {}
    if settings.ollama_embed_api_key:
        headers["Authorization"] = f"Bearer {settings.ollama_embed_api_key}"
    return Client(host=settings.ollama_embed_base_url, headers=headers or None)


def gerar_embeddings_em_lotes(
    textos: list[str],
) -> Iterator[tuple[int, list[str], list[list[float]]]]:
    """Gera embeddings lote a lote, cedendo (offset, lote, embeddings) por lote.

    Permite ao chamador persistir o progresso conforme os lotes chegam, em vez de
    acumular o documento inteiro em memória. Levanta exceção se a dimensão divergir
    do configurado.
    """
    if not textos:
        return
    settings = get_settings()
    client = get_embed_client()

    for i in range(0, len(textos), _BATCH_SIZE):
        lote = textos[i : i + _BATCH_SIZE]
        resp = client.embed(model=settings.ollama_embed_model, input=lote)
        embeddings = (
            resp.get("embeddings") if isinstance(resp, dict) else getattr(resp, "embeddings", None)
        )
        if not embeddings or len(embeddings) != len(lote):
            raise RuntimeError(
                f"Ollama retornou {len(embeddings or [])} embeddings para lote de {len(lote)}"
            )
        vetores = [list(e) for e in embeddings]
        dim = len(vetores[0])
        if dim != settings.embedding_dim:
            raise RuntimeError(
                f"Dimensão do embedding ({dim}) difere do configurado ({settings.embedding_dim}). "
                f"Verifique OLLAMA_EMBED_MODEL/EMBEDDING_DIM."
            )
        yield i, lote, vetores


def gerar_embeddings(textos: list[str]) -> list[list[float]]:
    """Gera embeddings de todos os textos de uma vez. Use apenas para listas pequenas
    (ex.: a pergunta do usuário); documentos inteiros devem usar
    `gerar_embeddings_em_lotes`."""
    resultado: list[list[float]] = []
    for _, _, vetores in gerar_embeddings_em_lotes(textos):
        resultado.extend(vetores)
    return resultado


def vetor_para_literal(vetor: list[float]) -> str:
    """Formata vetor como literal pgvector: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vetor) + "]"


# Fim de sentença (.!?;) seguido de espaço, ou quebra de linha (linhas de
# planilha/tabela não têm pontuação — cada linha vira uma "frase").
_SEPARADOR_SENTENCA = re.compile(r"(?<=[.!?;])\s+|\n+")


def dividir_em_chunks(texto: str, tamanho_max: int, tamanho_min: int) -> list[str]:
    """Divide texto em chunks de UMA frase.

    Fragmentos curtos (títulos, numeração de cláusula como "1.1.") são agregados
    à(s) frase(s) seguinte(s) até atingir `tamanho_min` — evita chunks sem conteúdo.
    Frases maiores que `tamanho_max` são fatiadas em janelas no espaço mais próximo.
    """
    frases = [re.sub(r"\s+", " ", f).strip() for f in _SEPARADOR_SENTENCA.split(texto)]
    frases = [f for f in frases if f]

    chunks: list[str] = []
    atual = ""
    for frase in frases:
        atual = f"{atual} {frase}".strip() if atual else frase
        if len(atual) >= tamanho_min:
            if len(atual) > tamanho_max:
                chunks.extend(_fatiar_frase_longa(atual, tamanho_max))
            else:
                chunks.append(atual)
            atual = ""

    if atual:
        # Sobra curta no fim: anexa ao último chunk para não criar fragmento solto.
        if chunks and len(atual) < tamanho_min:
            chunks[-1] = f"{chunks[-1]} {atual}"
        else:
            chunks.append(atual)
    return chunks


def _fatiar_frase_longa(frase: str, tamanho_max: int) -> list[str]:
    """Fatia frase acima do limite em janelas, cortando no espaço mais próximo."""
    pedacos: list[str] = []
    inicio = 0
    total = len(frase)
    while inicio < total:
        fim = min(inicio + tamanho_max, total)
        if fim < total:
            corte = frase.rfind(" ", inicio + tamanho_max // 2, fim)
            if corte > inicio:
                fim = corte
        pedaco = frase[inicio:fim].strip()
        if pedaco:
            pedacos.append(pedaco)
        inicio = fim + 1 if fim < total else total
    return pedacos

"""Avaliação do RAG de documentos contra o anexo de exemplo.

Requer infraestrutura real (banco com chunks ingeridos, Ollama local p/ embeddings
e Ollama nuvem p/ LLM). Habilite com:

    RUN_LLM_EVAL=1 EVAL_CONTRATO_ID=<id> pytest tests/eval -m integration -v

O contrato indicado em EVAL_CONTRATO_ID deve ter o PDF de exemplo
(docs/anexo-contrato-exemplo/contrato_0412025_...pdf) já ingerido — anexe-o pelo
sistema ou use POST /api/v1/contratos/{id}/documentos/ingestao.

Critérios:
- tipo=correta  → todos os grupos de `keywords_esperadas` presentes na resposta
                  (cada grupo aceita alternativas; case-insensitive).
- tipo=errada   → nenhuma `keywords_proibidas` presente na resposta (o LLM não
                  pode confirmar o fato errado).
"""

import json
import logging
import os
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration

_DATASET = Path(__file__).parent / "dataset_contrato_exemplo.json"

_RODAR = os.getenv("RUN_LLM_EVAL", "0") == "1"
_CONTRATO_ID = int(os.getenv("EVAL_CONTRATO_ID", "0"))

# Mínimo aceitável: LLMs não são determinísticos; exige-se alta taxa, não perfeição.
_TAXA_MINIMA_CORRETAS = 0.9
_TAXA_MINIMA_ERRADAS = 0.9


def _carregar_perguntas() -> list[dict]:
    return json.loads(_DATASET.read_text(encoding="utf-8"))["perguntas"]


def _responder(engine, contrato_id: int, pergunta: str) -> str:
    """RAG completo: busca semântica (bge-m3 local) + síntese (LLM nuvem, sem stream)."""
    from app.config import get_settings
    from app.services.query_engine import get_ollama_client
    from app.services.tools.documentos_contrato import _handler

    resultado = _handler(engine=engine, contrato_id=contrato_id, pergunta=pergunta)
    assert resultado.get("encontrado"), "Nenhum chunk encontrado — PDF de exemplo foi ingerido?"

    contexto = "\n\n".join(
        f"--- Trecho {i} (arquivo: {t['arquivo']}) ---\n{t['texto']}"
        for i, t in enumerate(resultado["trechos"], start=1)
    )
    prompt = (
        "Você é o assistente de documentos do NexusGov. Responda em português do Brasil.\n"
        f"{resultado['instrucao']}\n\n"
        f"[Trechos dos documentos]\n{contexto}\n[Fim dos trechos]\n\n"
        f"Pergunta: {pergunta}"
    )

    settings = get_settings()
    resp = get_ollama_client().chat(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        think=False,
    )
    msg = resp.get("message") if isinstance(resp, dict) else getattr(resp, "message", None)
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
    return content or ""


@pytest.fixture(scope="module")
def engine():
    if not _RODAR:
        pytest.skip("RUN_LLM_EVAL != 1")
    if not _CONTRATO_ID:
        pytest.skip("EVAL_CONTRATO_ID não definido")
    from app.services.database import create_engine_db

    eng = create_engine_db()
    yield eng
    eng.dispose()


def test_perguntas_corretas(engine):
    perguntas = [p for p in _carregar_perguntas() if p["tipo"] == "correta"]
    falhas = []
    for p in perguntas:
        resposta = _responder(engine, _CONTRATO_ID, p["pergunta"])
        resposta_lower = resposta.lower()
        grupos_ok = all(
            any(alt.lower() in resposta_lower for alt in grupo)
            for grupo in p["keywords_esperadas"]
        )
        logger.info("[%s] %s → %s | ok=%s", p["id"], p["pergunta"], resposta[:200], grupos_ok)
        if not grupos_ok:
            falhas.append(
                f"#{p['id']} {p['pergunta']!r}: esperado {p['keywords_esperadas']}, "
                f"resposta: {resposta[:300]!r}"
            )
    taxa = 1 - len(falhas) / len(perguntas)
    assert taxa >= _TAXA_MINIMA_CORRETAS, (
        f"Taxa de acerto {taxa:.0%} abaixo de {_TAXA_MINIMA_CORRETAS:.0%}.\n" + "\n".join(falhas)
    )


def test_perguntas_erradas_nao_confirmadas(engine):
    perguntas = [p for p in _carregar_perguntas() if p["tipo"] == "errada"]
    falhas = []
    for p in perguntas:
        resposta = _responder(engine, _CONTRATO_ID, p["pergunta"])
        resposta_lower = resposta.lower()
        confirmou_erro = any(kw.lower() in resposta_lower for kw in p["keywords_proibidas"])
        logger.info(
            "[%s] %s → %s | confirmou_erro=%s", p["id"], p["pergunta"], resposta[:200], confirmou_erro
        )
        if confirmou_erro:
            falhas.append(
                f"#{p['id']} {p['pergunta']!r}: resposta contém termo da resposta errada "
                f"{p['keywords_proibidas']}: {resposta[:300]!r}"
            )
    taxa = 1 - len(falhas) / len(perguntas)
    assert taxa >= _TAXA_MINIMA_ERRADAS, (
        f"Taxa {taxa:.0%} abaixo de {_TAXA_MINIMA_ERRADAS:.0%}.\n" + "\n".join(falhas)
    )

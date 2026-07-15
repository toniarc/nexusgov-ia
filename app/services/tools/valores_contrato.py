from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.tools.base import ToolSpec


class _Args(BaseModel):
    pass


_SQL = text(
    """
    SELECT c.numero,
           c.ano,
           c.valor_global,
           c.quantidade_max_postos
      FROM nexusgov.contrato c
     WHERE c.id = :contrato_id
     LIMIT 1
    """
)


def _handler(engine: Engine, contrato_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        result = conn.execute(_SQL, {"contrato_id": contrato_id})
        cols = list(result.keys())
        row = result.fetchone()
    if row is None:
        return {"encontrado": False}
    return {"encontrado": True, **{c: row[i] for i, c in enumerate(cols)}}


SPEC = ToolSpec(
    name="valores_contrato",
    description=(
        "Retorna os valores financeiros do contrato ativo: valor global e quantidade máxima de "
        "postos. O contrato registra APENAS o valor global — não há valor mensal nem anual. "
        "Use para perguntas focadas em valores como 'qual o valor do contrato', 'quanto vale', "
        "'valor global', e também para 'valor mensal'/'valor anual' (responda que o contrato "
        "só possui valor global)."
    ),
    args_model=_Args,
    handler=_handler,
)

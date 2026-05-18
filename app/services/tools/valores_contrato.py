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
           c.valor_mensal,
           c.valor_anual,
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
        "Retorna apenas os valores financeiros do contrato ativo: valor mensal, valor anual, "
        "valor global e quantidade máxima de postos. Use para perguntas focadas em valores como "
        "'qual o valor do contrato', 'valor mensal', 'quanto vale', 'valor global'."
    ),
    args_model=_Args,
    handler=_handler,
)

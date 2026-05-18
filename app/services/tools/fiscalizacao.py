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
           ut.nome  AS fiscal_titular_nome,
           ut.email AS fiscal_titular_email,
           ut.cpf   AS fiscal_titular_cpf,
           ut.matricula AS fiscal_titular_matricula,
           ft.vinculo AS fiscal_titular_vinculo,
           ft.tipo  AS fiscal_titular_tipo,
           us.nome  AS fiscal_suplente_nome,
           us.email AS fiscal_suplente_email,
           us.cpf   AS fiscal_suplente_cpf,
           us.matricula AS fiscal_suplente_matricula,
           fs.vinculo AS fiscal_suplente_vinculo,
           fs.tipo  AS fiscal_suplente_tipo
      FROM nexusgov.contrato c
      LEFT JOIN nexusgov.fiscal  ft ON ft.id = c.fiscal_titular_id
      LEFT JOIN nexusgov.usuario ut ON ut.id = ft.usuario_id
      LEFT JOIN nexusgov.fiscal  fs ON fs.id = c.fiscal_suplente_id
      LEFT JOIN nexusgov.usuario us ON us.id = fs.usuario_id
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
    name="fiscalizacao",
    description=(
        "Retorna dados de fiscalização do contrato ativo: fiscal titular e fiscal suplente, "
        "com nome, email, CPF, matrícula, vínculo e tipo. Use para perguntas como "
        "'quem é o fiscal', 'fiscal titular', 'quem fiscaliza', 'dados do fiscal', "
        "'fiscal suplente'."
    ),
    args_model=_Args,
    handler=_handler,
)

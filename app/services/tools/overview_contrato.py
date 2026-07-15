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
           c.status,
           c.processo_administrativo,
           c.objeto_resumido,
           c.inicio,
           c.fim,
           c.valor_global,
           c.quantidade_max_postos,
           f.razao_social   AS fornecedor_razao_social,
           f.cnpj           AS fornecedor_cnpj,
           ut.nome          AS fiscal_titular_nome,
           ut.email         AS fiscal_titular_email,
           us.nome          AS fiscal_suplente_nome,
           us.email         AS fiscal_suplente_email,
           fc.nome          AS modalidade_licitatoria,
           co.nome          AS categoria_objeto,
           un.nome          AS unidade_nome
      FROM nexusgov.contrato c
      LEFT JOIN nexusgov.fornecedor f ON f.id = c.fornecedor_id
      LEFT JOIN nexusgov.fiscal  ft ON ft.id = c.fiscal_titular_id
      LEFT JOIN nexusgov.usuario ut ON ut.id = ft.usuario_id
      LEFT JOIN nexusgov.fiscal  fs ON fs.id = c.fiscal_suplente_id
      LEFT JOIN nexusgov.usuario us ON us.id = fs.usuario_id
      LEFT JOIN nexusgov.forma_contratacao fc ON fc.id = c.modalidade_licitatoria_id
      LEFT JOIN nexusgov.categoria_objeto   co ON co.id = c.categoria_objeto_id
      LEFT JOIN nexusgov.unidade            un ON un.id = c.unidade_id
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
    name="overview_contrato",
    description=(
        "Retorna dados gerais do contrato ativo: número/ano, status, processo administrativo, "
        "objeto, vigência (início/fim), valor global, quantidade máxima de postos, modalidade "
        "licitatória, categoria do objeto, unidade, dados do fornecedor contratado (razão social "
        "e CNPJ) e fiscais titular e suplente (nome e email). Use para perguntas genéricas como "
        "'me fale sobre o contrato', 'dados do contrato', 'resumo do contrato', "
        "'me mostra o contrato'."
    ),
    args_model=_Args,
    handler=_handler,
)

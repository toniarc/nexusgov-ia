from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.tools.base import ToolSpec


class _Args(BaseModel):
    incluir_inativos: bool = Field(
        default=False,
        description="Se True, inclui também postos sem vínculos ativos. Default False.",
    )


_SQL_RESUMO = text(
    """
    SELECT c.quantidade_max_postos,
           COUNT(DISTINCT pt.id)                                                AS total_postos,
           COUNT(DISTINCT pt.id) FILTER (WHERE vp.colaborador_id IS NOT NULL)   AS postos_com_vinculo
      FROM nexusgov.contrato c
      LEFT JOIN nexusgov.posto_trabalho pt ON pt.contrato_id = c.id
      LEFT JOIN nexusgov.vinculo_posto   vp ON vp.posto_trabalho_id = pt.id
                                            AND vp.situacao = 'ATIVO'
     WHERE c.id = :contrato_id
     GROUP BY c.quantidade_max_postos
    """
)


_SQL_DETALHE = text(
    """
    SELECT pt.id              AS posto_id,
           cat.funcao         AS categoria_funcao,
           cat.quantidade     AS categoria_quantidade,
           cat.valor          AS categoria_valor,
           la.nome            AS local_atuacao_nome,
           la.codigo          AS local_atuacao_codigo,
           u.nome             AS unidade_nome,
           m.nome             AS municipio_nome,
           est.uf             AS estado_uf,
           pt.hora_inicio,
           pt.hora_fim,
           COUNT(vp.colaborador_id) FILTER (WHERE vp.situacao = 'ATIVO') AS colaboradores_ativos
      FROM nexusgov.posto_trabalho pt
      LEFT JOIN nexusgov.categoria_posto_trabalho cat ON cat.id = pt.categoria_posto_id
      LEFT JOIN nexusgov.local_atuacao la             ON la.id = pt.local_atuacao_id
      LEFT JOIN nexusgov.unidade      u               ON u.id  = la.unidade_id
      LEFT JOIN nexusgov.municipio    m               ON m.id  = la.municipio_id
      LEFT JOIN nexusgov.estado       est             ON est.id = m.estado_id
      LEFT JOIN nexusgov.vinculo_posto vp             ON vp.posto_trabalho_id = pt.id
     WHERE pt.contrato_id = :contrato_id
     GROUP BY pt.id, cat.funcao, cat.quantidade, cat.valor,
              la.nome, la.codigo, u.nome, m.nome, est.uf, pt.hora_inicio, pt.hora_fim
     HAVING (:incluir_inativos OR COUNT(vp.colaborador_id) FILTER (WHERE vp.situacao = 'ATIVO') > 0)
     ORDER BY la.nome, cat.funcao
     LIMIT 200
    """
)


def _handler(engine: Engine, contrato_id: int, incluir_inativos: bool = False) -> dict[str, Any]:
    with engine.connect() as conn:
        resumo_res = conn.execute(_SQL_RESUMO, {"contrato_id": contrato_id})
        resumo_cols = list(resumo_res.keys())
        resumo_row = resumo_res.fetchone()

        det_res = conn.execute(
            _SQL_DETALHE,
            {"contrato_id": contrato_id, "incluir_inativos": incluir_inativos},
        )
        det_cols = list(det_res.keys())
        det_rows = det_res.fetchall()

    resumo = {c: resumo_row[i] for i, c in enumerate(resumo_cols)} if resumo_row else {
        "quantidade_max_postos": None,
        "total_postos": 0,
        "postos_com_vinculo": 0,
    }
    postos = [{c: r[i] for i, c in enumerate(det_cols)} for r in det_rows]
    return {"resumo": resumo, "postos": postos}


SPEC = ToolSpec(
    name="postos_trabalho",
    description=(
        "Retorna postos de trabalho do contrato ativo: resumo (máximo permitido, total, "
        "ativos) e lista detalhada por posto (função/categoria, valor, local de atuação, "
        "unidade, município/UF, horário e número de colaboradores ativos). Use para perguntas "
        "como 'quantos postos', 'postos de trabalho', 'lista de postos', 'onde estão os postos'."
    ),
    args_model=_Args,
    handler=_handler,
)

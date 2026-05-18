import logging
import re

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Casa "contrato 2024/1", "nº 2024/1", "n° 2024/1", "2024/1" em começo ou após espaço/pontuação,
# exigindo contexto que reduz falsos positivos vs. datas ("12/2024") e frações.
_PATTERN = re.compile(
    r"(?:\bcontrato[s]?\s+(?:n[º°o]\s*)?|\bn[º°o]\s*|^|(?<=[\s,;:.!?]))"
    r"(\d{4})\s*/\s*(\d{1,6})\b",
    re.IGNORECASE,
)

_PERMISSION_SQL = text(
    """
    SELECT c.id
      FROM nexusgov.contrato c
     WHERE c.ano = :ano
       AND c.numero = :numero
    """
)


def extrair_referencia_contrato(texto: str) -> tuple[int, int] | None:
    """Retorna (ano, numero) se padrão de referência contratual for encontrado."""
    match = _PATTERN.search(texto)
    if not match:
        return None
    ano = int(match.group(1))
    if ano < 1900 or ano > 2999:
        return None
    return ano, int(match.group(2))


def resolver_contrato(ano: int, numero: int, usuario_id: int, engine: Engine) -> int | None:
    """Busca contrato_id pelo ano/numero. Acesso liberado para qualquer usuário logado."""
    with engine.connect() as conn:
        row = conn.execute(
            _PERMISSION_SQL,
            {"ano": ano, "numero": numero},
        ).fetchone()
    if row is None:
        logger.info("Contrato %s/%s não encontrado (usuario_id=%s)", ano, numero, usuario_id)
        return None
    return row[0]

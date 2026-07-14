from datetime import datetime

from pydantic import BaseModel


class IngestaoAnexoStatus(BaseModel):
    anexo_id: int
    nome_arquivo: str | None
    tipo: str | None
    descricao: str | None
    status: str
    num_chunks: int | None
    erro: str | None
    tentativas: int | None
    alterado_em: datetime | None


class IngestaoContratoResponse(BaseModel):
    contrato_id: int
    anexos: list[IngestaoAnexoStatus]


class ReprocessarResponse(BaseModel):
    contrato_id: int
    reprocessando: int
    mensagem: str

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=2000)


class ContratoAtivo(BaseModel):
    ano: int
    numero: int


class ChatResponse(BaseModel):
    usuario_id: int
    contrato_ativo: ContratoAtivo | None
    resposta_markdown: str
    resposta_html: str
    aguardando_contrato: bool

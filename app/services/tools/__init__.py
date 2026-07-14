from typing import Any

from sqlalchemy.engine import Engine

from app.services.tools.base import ToolSpec
from app.services.tools.documentos_contrato import SPEC as _DOCUMENTOS
from app.services.tools.fiscalizacao import SPEC as _FISCALIZACAO
from app.services.tools.overview_contrato import SPEC as _OVERVIEW
from app.services.tools.postos_trabalho import SPEC as _POSTOS
from app.services.tools.valores_contrato import SPEC as _VALORES


REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (_OVERVIEW, _VALORES, _FISCALIZACAO, _POSTOS, _DOCUMENTOS)
}


def ollama_tool_definitions() -> list[dict[str, Any]]:
    return [spec.to_ollama_tool() for spec in REGISTRY.values()]


def dispatch(name: str, raw_args: dict[str, Any], engine: Engine, contrato_id: int) -> dict[str, Any]:
    spec = REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"tool desconhecida: {name}")
    return spec.call(engine, contrato_id, raw_args)


__all__ = ["REGISTRY", "ToolSpec", "ollama_tool_definitions", "dispatch"]

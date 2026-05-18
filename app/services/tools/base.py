from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.engine import Engine


ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler

    def to_ollama_tool(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                    "additionalProperties": False,
                },
            },
        }

    def call(self, engine: Engine, contrato_id: int, raw_args: dict[str, Any]) -> dict[str, Any]:
        args = self.args_model.model_validate(raw_args or {})
        return self.handler(engine=engine, contrato_id=contrato_id, **args.model_dump())

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from llama_index.core import SQLDatabase
from llama_index.core.objects import ObjectIndex
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.config import get_settings
from app.prompts.system_pt_br import (
    build_synthesis_prompt_template,
    build_tool_router_prompt,
    get_aguardando_contrato_msg,
)
from app.services.contract_resolver import extrair_referencia_contrato, resolver_contrato
from app.services.markdown_renderer import render
from app.services.query_engine import build_query_engine, get_ollama_client
from app.services.session_store import SessionState, SessionStore
from app.services.tools import REGISTRY, dispatch, ollama_tool_definitions

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    event: str
    data: dict[str, Any]


class ChatService:
    def __init__(
        self,
        sql_database: SQLDatabase,
        table_object_index: ObjectIndex,
        session_store: SessionStore,
    ):
        self._sql_database = sql_database
        self._table_object_index = table_object_index
        self._sessions = session_store

    async def processar_mensagem_stream(
        self, usuario_id: int, mensagem: str
    ) -> AsyncIterator[StreamEvent]:
        session = self._sessions.get_or_create(usuario_id)

        referencia = extrair_referencia_contrato(mensagem)
        if referencia:
            ano, numero = referencia
            contrato_id = await asyncio.to_thread(
                resolver_contrato, ano, numero, usuario_id, self._sql_database.engine
            )
            if contrato_id is None:
                md = (
                    f"Não encontrei o contrato **{ano}/{numero}** ou você não possui acesso. "
                    "Verifique o ano, o número e suas permissões."
                )
                self._sessions.update(session)
                yield self._meta_event(usuario_id, session, aguardando=session.contrato_id is None)
                yield StreamEvent("content", {"delta": md})
                yield self._done_event(md)
                return
            if contrato_id != session.contrato_id:
                logger.info("Sessão %s: trocando contrato para %s/%s", usuario_id, ano, numero)
                session.atualizar_contrato(contrato_id, ano, numero)

        if session.contrato_id is None:
            md = get_aguardando_contrato_msg()
            self._sessions.update(session)
            yield self._meta_event(usuario_id, session, aguardando=True)
            yield StreamEvent("content", {"delta": md})
            yield self._done_event(md)
            return

        session.adicionar_mensagem("user", mensagem)
        historico = session.historico_recente(n=6)

        yield self._meta_event(usuario_id, session, aguardando=False)

        try:
            tool_outcome = None
            if get_settings().chat_tool_calling_enabled:
                tool_outcome = await self._resolve_tool(session, historico[:-1], mensagem)

            if tool_outcome is not None:
                tool_name, tool_args, result_dict = tool_outcome
                logger.info(
                    "Sessão %s: tool=%s args=%s", usuario_id, tool_name, tool_args
                )
                sql_query = f"tool:{tool_name}({json.dumps(tool_args, ensure_ascii=False)})"
                result_str = _format_tool_result(result_dict)
            else:
                logger.info("Sessão %s: fallback para LLM-SQL livre", usuario_id)
                sql_query, result_str = await asyncio.to_thread(
                    self._executar_sql, session, historico[:-1], mensagem
                )
        except _ChatError as err:
            self._sessions.update(session)
            yield StreamEvent("error", {"mensagem": err.message})
            yield StreamEvent("content", {"delta": err.message})
            yield self._done_event(err.message)
            return

        synth_template = build_synthesis_prompt_template(
            session.contrato_ano, session.contrato_numero
        )
        prompt_text = synth_template.format(
            query_str=mensagem, sql_query=sql_query, context_str=result_str
        )

        full_content = ""
        try:
            async for kind, delta in self._stream_synthesis(prompt_text):
                if kind == "thinking":
                    yield StreamEvent("thinking", {"delta": delta})
                else:
                    full_content += delta
                    yield StreamEvent("content", {"delta": delta})
        except (httpx.TimeoutException, TimeoutError):
            logger.exception("Timeout no LLM (usuario_id=%s)", usuario_id)
            full_content = "O serviço de IA demorou demais para responder. Tente uma pergunta mais simples."
            yield StreamEvent("error", {"mensagem": full_content})
            yield StreamEvent("content", {"delta": full_content})
        except httpx.HTTPError:
            logger.exception("Falha de rede com LLM (usuario_id=%s)", usuario_id)
            full_content = "Não foi possível contatar o serviço de IA agora. Tente novamente."
            yield StreamEvent("error", {"mensagem": full_content})
            yield StreamEvent("content", {"delta": full_content})
        except Exception:
            logger.exception("Erro inesperado na síntese (usuario_id=%s)", usuario_id)
            full_content = "Desculpe, ocorreu um erro ao processar sua pergunta. Tente novamente."
            yield StreamEvent("error", {"mensagem": full_content})
            yield StreamEvent("content", {"delta": full_content})

        session.adicionar_mensagem("assistant", full_content)
        self._sessions.update(session)
        yield self._done_event(full_content)

    def _executar_sql(
        self, session: SessionState, historico: list[dict], mensagem: str
    ) -> tuple[str, str]:
        engine = build_query_engine(
            sql_database=self._sql_database,
            table_object_index=self._table_object_index,
            contrato_id=session.contrato_id,
            contrato_ano=session.contrato_ano,
            contrato_numero=session.contrato_numero,
            historico_recente=historico,
            synthesize=False,
        )
        try:
            response = engine.query(mensagem)
        except OperationalError as e:
            logger.exception("Banco indisponível (usuario_id=%s)", session.usuario_id)
            raise _ChatError(
                "O banco de dados está temporariamente indisponível. Tente novamente em instantes."
            ) from e
        except SQLAlchemyError as e:
            logger.exception("Erro de SQL (usuario_id=%s)", session.usuario_id)
            raise _ChatError(
                "A consulta gerada não pôde ser executada. Reformule sua pergunta."
            ) from e
        except (httpx.TimeoutException, TimeoutError) as e:
            logger.exception("Timeout no LLM (usuario_id=%s)", session.usuario_id)
            raise _ChatError(
                "O serviço de IA demorou demais para responder. Tente uma pergunta mais simples."
            ) from e
        except httpx.HTTPError as e:
            logger.exception("Falha de rede com LLM (usuario_id=%s)", session.usuario_id)
            raise _ChatError(
                "Não foi possível contatar o serviço de IA agora. Tente novamente."
            ) from e
        except Exception as e:
            logger.exception("Erro inesperado no SQL (usuario_id=%s)", session.usuario_id)
            raise _ChatError(
                "Desculpe, ocorreu um erro ao processar sua pergunta. Tente novamente."
            ) from e

        metadata = getattr(response, "metadata", None) or {}
        sql_query = metadata.get("sql_query", "")
        result_str = str(response)
        return sql_query, result_str

    async def _resolve_tool(
        self, session: SessionState, historico: list[dict], mensagem: str
    ) -> tuple[str, dict, dict] | None:
        """Pergunta ao LLM qual tool chamar. Retorna (name, args, result_dict) ou None."""
        router_prompt = build_tool_router_prompt(
            session.contrato_ano, session.contrato_numero
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": router_prompt}]
        for msg in historico:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": mensagem})

        try:
            response = await asyncio.to_thread(self._chamar_router_llm, messages)
        except (httpx.HTTPError, TimeoutError):
            logger.exception("Falha no router de tools (usuario_id=%s)", session.usuario_id)
            return None
        except Exception:
            logger.exception("Erro inesperado no router (usuario_id=%s)", session.usuario_id)
            return None

        msg_obj = response.get("message") if isinstance(response, dict) else getattr(response, "message", None)
        if msg_obj is None:
            return None
        tool_calls = (
            msg_obj.get("tool_calls") if isinstance(msg_obj, dict) else getattr(msg_obj, "tool_calls", None)
        )
        if not tool_calls:
            return None

        first = tool_calls[0]
        fn = first.get("function") if isinstance(first, dict) else getattr(first, "function", None)
        if fn is None:
            return None
        name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
        raw_args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", None)

        if not name or name not in REGISTRY:
            logger.warning("Tool desconhecida retornada pelo LLM: %r", name)
            return None

        if isinstance(raw_args, str):
            try:
                args_dict = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                logger.warning("Args inválidos do LLM para tool %s: %r", name, raw_args)
                return None
        elif isinstance(raw_args, dict):
            args_dict = raw_args
        else:
            args_dict = {}

        try:
            result_dict = await asyncio.to_thread(
                dispatch, name, args_dict, self._sql_database.engine, session.contrato_id
            )
        except ValidationError:
            logger.warning("Args rejeitados para tool %s: %r", name, args_dict)
            return None
        except (OperationalError, SQLAlchemyError):
            logger.exception("Erro de BD na tool %s", name)
            raise _ChatError(
                "O banco de dados está temporariamente indisponível. Tente novamente em instantes."
            )
        except Exception:
            logger.exception("Erro inesperado na tool %s", name)
            return None

        return name, args_dict, result_dict

    def _chamar_router_llm(self, messages: list[dict[str, Any]]) -> Any:
        settings = get_settings()
        client = get_ollama_client()
        return client.chat(
            model=settings.ollama_model,
            messages=messages,
            tools=ollama_tool_definitions(),
            stream=False,
            think=False,
        )

    async def _stream_synthesis(self, prompt_text: str) -> AsyncIterator[tuple[str, str]]:
        settings = get_settings()
        client = get_ollama_client()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def _worker() -> None:
            try:
                stream = client.chat(
                    model=settings.ollama_model,
                    messages=[{"role": "user", "content": prompt_text}],
                    think=True,
                    stream=True,
                )
                for chunk in stream:
                    msg = chunk.get("message") if isinstance(chunk, dict) else getattr(chunk, "message", None)
                    if msg is None:
                        continue
                    thinking = (
                        msg.get("thinking") if isinstance(msg, dict) else getattr(msg, "thinking", None)
                    )
                    content = (
                        msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
                    )
                    if thinking:
                        asyncio.run_coroutine_threadsafe(queue.put(("thinking", thinking)), loop)
                    if content:
                        asyncio.run_coroutine_threadsafe(queue.put(("content", content)), loop)
                asyncio.run_coroutine_threadsafe(queue.put(("__done__", None)), loop)
            except BaseException as exc:
                asyncio.run_coroutine_threadsafe(queue.put(("__error__", exc)), loop)

        threading.Thread(target=_worker, daemon=True).start()

        while True:
            kind, payload = await queue.get()
            if kind == "__done__":
                return
            if kind == "__error__":
                raise payload  # type: ignore[misc]
            yield kind, payload

    def _meta_event(self, usuario_id: int, session: SessionState, aguardando: bool) -> StreamEvent:
        contrato = self._contrato_ativo(session)
        return StreamEvent(
            "meta",
            {
                "usuario_id": usuario_id,
                "contrato_ativo": contrato,
                "aguardando_contrato": aguardando,
            },
        )

    @staticmethod
    def _done_event(markdown: str) -> StreamEvent:
        return StreamEvent(
            "done",
            {"resposta_markdown": markdown, "resposta_html": render(markdown)},
        )

    @staticmethod
    def _contrato_ativo(session: SessionState) -> dict | None:
        if session.contrato_id is None:
            return None
        return {"ano": session.contrato_ano, "numero": session.contrato_numero}


class _ChatError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _format_tool_result(result: dict[str, Any]) -> str:
    """Serializa dict de tool como JSON pt-BR para o synthesis prompt."""
    return json.dumps(result, ensure_ascii=False, default=str, indent=2)

import logging
import re

from llama_index.core import Settings as LlamaSettings, SQLDatabase, VectorStoreIndex
from llama_index.core.indices.struct_store import SQLTableRetrieverQueryEngine
from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema
from llama_index.core.prompts import PromptTemplate
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from ollama import Client
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.prompts.system_pt_br import build_synthesis_prompt_template, build_system_prompt

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 100

_NEXUSGOV_TABLES = [
    "contrato",
    "fornecedor",
    "fornecedor_representante",
    "fiscal",
    "usuario",
    "usuario_perfil",
    "posto_trabalho",
    "categoria_posto_trabalho",
    "local_atuacao",
    "unidade",
    "municipio",
    "estado",
    "colaborador",
    "vinculo_posto",
    "atesto",
    "atesto_posto",
    "validacao_unidade",
    "validacao_fiscal_posto",
    "ordem_servico",
    "ordem_servico_item",
]

_SQL_PROMPT_TEMPLATE = """\
{system_context}

Dado o schema acima, gere uma query SQL PostgreSQL para responder à pergunta abaixo.
Retorne APENAS o SQL, sem explicações adicionais.

REGRAS OBRIGATÓRIAS:
- Sempre inclua `LIMIT {default_limit}` ao final, salvo agregações que retornem 1 linha.
- Filtre pelo contrato ativo conforme indicado no contexto de sistema.
- Nunca use INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/TRUNCATE.
- PROIBIDO selecionar colunas FK (`*_id`) no SELECT final. Sempre faça LEFT JOIN para resolver o nome/descrição da entidade referenciada.
- Para qualquer SELECT em `contrato`, JOIN OBRIGATÓRIO:
    LEFT JOIN nexusgov.fornecedor f ON f.id = c.fornecedor_id
    LEFT JOIN nexusgov.fiscal ft ON ft.id = c.fiscal_titular_id
    LEFT JOIN nexusgov.usuario ut ON ut.id = ft.usuario_id
    LEFT JOIN nexusgov.fiscal fs ON fs.id = c.fiscal_suplente_id
    LEFT JOIN nexusgov.usuario us ON us.id = fs.usuario_id
  E traga no SELECT: f.razao_social, f.cnpj, ut.nome, ut.email, us.nome, us.email.

Schema das tabelas disponíveis:
{schema}

{conversation_context}Pergunta: {query_str}

SQL:"""


def get_ollama_client() -> Client:
    """Factory de cliente Ollama com auth header já configurado."""
    settings = get_settings()
    return Client(
        host=settings.ollama_base_url,
        headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
    )


def configure_llama_globals() -> None:
    """Configura LLM e embedding globais do LlamaIndex. Chamado uma vez no startup.

    LLM: Ollama da nuvem (com API key). Embeddings: bge-m3 no Ollama local.
    """
    settings = get_settings()

    client = get_ollama_client()

    LlamaSettings.llm = Ollama(
        client=client,
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        request_timeout=settings.ollama_request_timeout,
        additional_kwargs={"Authorization": f"Bearer {settings.ollama_api_key}"},
    )

    LlamaSettings.embed_model = OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=settings.ollama_embed_base_url,
    )


class CachedSQLDatabase(SQLDatabase):
    """SQLDatabase com cache de get_single_table_info para evitar reflection repetida."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._table_info_cache: dict[str, str] = {}

    def get_single_table_info(self, table_name: str) -> str:
        cached = self._table_info_cache.get(table_name)
        if cached is not None:
            return cached
        info = super().get_single_table_info(table_name)
        self._table_info_cache[table_name] = info
        return info


def build_sql_database(engine: Engine) -> SQLDatabase:
    sql_db = CachedSQLDatabase(engine, include_tables=_NEXUSGOV_TABLES, schema="nexusgov")
    for t in _NEXUSGOV_TABLES:
        sql_db.get_single_table_info(t)
    return sql_db


def build_table_object_index(sql_database: SQLDatabase) -> ObjectIndex:
    """ObjectIndex para retrieval de tabelas relevantes por query."""
    mapping = SQLTableNodeMapping(sql_database)
    schemas = [SQLTableSchema(table_name=t) for t in _NEXUSGOV_TABLES]
    return ObjectIndex.from_objects(schemas, mapping, VectorStoreIndex)


_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_AGGREGATE_ONLY_RE = re.compile(
    r"^\s*select\s+(count|sum|avg|min|max)\s*\(", re.IGNORECASE
)


def enforce_limit(sql: str, default_limit: int = _DEFAULT_LIMIT) -> str:
    """Garante presença de LIMIT em queries não-agregadas."""
    stripped = sql.strip().rstrip(";")
    if _LIMIT_RE.search(stripped):
        return stripped
    if _AGGREGATE_ONLY_RE.search(stripped) and "group by" not in stripped.lower():
        return stripped
    return f"{stripped} LIMIT {default_limit}"


def build_query_engine(
    sql_database: SQLDatabase,
    table_object_index: ObjectIndex,
    contrato_id: int,
    contrato_ano: int,
    contrato_numero: int,
    historico_recente: list[dict],
    top_k_tables: int = 4,
    synthesize: bool = True,
) -> SQLTableRetrieverQueryEngine:
    system_context = build_system_prompt(contrato_id, contrato_ano, contrato_numero)

    conversation_context = ""
    if historico_recente:
        linhas = []
        for msg in historico_recente:
            role = "Usuário" if msg["role"] == "user" else "Assistente"
            linhas.append(f"{role}: {msg['content']}")
        conversation_context = (
            "[Histórico recente da conversa]\n" + "\n".join(linhas) + "\n[Fim do histórico]\n\n"
        )

    prompt = PromptTemplate(
        _SQL_PROMPT_TEMPLATE,
        template_var_mappings={"query_str": "query_str"},
        function_mappings={
            "system_context": lambda **_: system_context,
            "conversation_context": lambda **_: conversation_context,
            "schema": lambda **_: "",
            "default_limit": lambda **_: str(_DEFAULT_LIMIT),
        },
    )

    synthesis_template_str = build_synthesis_prompt_template(contrato_ano, contrato_numero)
    synthesis_prompt = PromptTemplate(synthesis_template_str)

    engine = SQLTableRetrieverQueryEngine(
        sql_database=sql_database,
        table_retriever=table_object_index.as_retriever(similarity_top_k=top_k_tables),
        synthesize_response=synthesize,
        verbose=True,
    )
    prompts: dict = {"text_to_sql_prompt": prompt}
    if synthesize:
        prompts["response_synthesis_prompt"] = synthesis_prompt
    engine.update_prompts(prompts)
    return engine

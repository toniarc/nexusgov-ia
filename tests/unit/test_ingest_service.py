"""Ingestão incremental: chunks gravados lote a lote, com heartbeat de progresso."""

from unittest.mock import patch

import pytest

from app.services import ingest_service


class _FakeConn:
    """Coleta as execuções SQL de uma transação."""

    def __init__(self, registro):
        self._registro = registro

    def execute(self, stmt, params=None):
        self._registro.append((str(stmt).strip(), params or {}))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    """Engine mínimo que registra cada transação (engine.begin()) separadamente."""

    def __init__(self):
        self.transacoes = []

    def begin(self):
        registro = []
        self.transacoes.append(registro)
        return _FakeConn(registro)


def _sql_de(engine):
    return [sql for transacao in engine.transacoes for sql, _ in transacao]


def _params_de(engine, trecho):
    return [
        params
        for transacao in engine.transacoes
        for sql, params in transacao
        if trecho in sql
    ]


@pytest.fixture
def chunks_e_embeddings():
    # 3 lotes: offsets 0, 2 e 4 (lotes de 2 chunks).
    return [
        (0, ["frase 0", "frase 1"], [[0.1], [0.2]]),
        (2, ["frase 2", "frase 3"], [[0.3], [0.4]]),
        (4, ["frase 4"], [[0.5]]),
    ]


def _ingerir(engine, lotes):
    with patch.object(ingest_service, "baixar_anexo", return_value=b"pdf"), patch.object(
        ingest_service, "extrair_texto", return_value="texto"
    ), patch.object(
        ingest_service, "dividir_em_chunks", return_value=["f"] * 5
    ), patch.object(
        ingest_service, "gerar_embeddings_em_lotes", return_value=iter(lotes)
    ):
        return ingest_service._ingerir_anexo(engine, anexo_id=9, contrato_id=1, nome_arquivo="a.pdf", arquivo_key="k")


def test_chunks_gravados_por_lote_e_nao_so_no_fim(chunks_e_embeddings):
    engine = _FakeEngine()
    total = _ingerir(engine, chunks_e_embeddings)

    assert total == 5
    # 1 transação para limpar + 1 por lote (3) = 4. O código antigo fazia 2
    # (limpeza + gravação única no fim), perdendo tudo se interrompido.
    assert len(engine.transacoes) == 4


def test_heartbeat_em_cada_lote():
    engine = _FakeEngine()
    lotes = [
        (0, ["frase 0", "frase 1"], [[0.1], [0.2]]),
        (2, ["frase 2"], [[0.3]]),
    ]
    _ingerir(engine, lotes)

    heartbeats = [sql for sql in _sql_de(engine) if "ingestao_em = now()" in sql]
    assert len(heartbeats) == 2, "cada lote deve marcar progresso em ingestao_em"


def test_heartbeat_vai_junto_com_os_inserts_do_lote():
    engine = _FakeEngine()
    _ingerir(engine, [(0, ["frase 0"], [[0.1]])])

    # Última transação = lote: insere o chunk e marca progresso atomicamente.
    ultima = engine.transacoes[-1]
    sqls = [sql for sql, _ in ultima]
    assert any("INSERT INTO nexusgov.contrato_documento_chunk" in s for s in sqls)
    assert any("ingestao_em = now()" in s for s in sqls)


def test_chunk_index_continua_entre_lotes(chunks_e_embeddings):
    engine = _FakeEngine()
    _ingerir(engine, chunks_e_embeddings)

    indices = [p["chunk_index"] for p in _params_de(engine, "INSERT INTO")]
    assert indices == [0, 1, 2, 3, 4], "offset do lote deve continuar a numeração global"


def test_limpa_chunks_antigos_antes_de_gravar(chunks_e_embeddings):
    engine = _FakeEngine()
    _ingerir(engine, chunks_e_embeddings)

    sqls = _sql_de(engine)
    assert "DELETE" in sqls[0], "reprocessamento deve limpar chunks anteriores primeiro"


def test_sem_texto_extraido_levanta_e_nao_grava():
    engine = _FakeEngine()
    with patch.object(ingest_service, "baixar_anexo", return_value=b"pdf"), patch.object(
        ingest_service, "extrair_texto", return_value=""
    ), patch.object(ingest_service, "dividir_em_chunks", return_value=[]):
        with pytest.raises(RuntimeError, match="Nenhum texto extraído"):
            ingest_service._ingerir_anexo(engine, 9, 1, "a.pdf", "k")

    assert engine.transacoes == [], "não deve tocar no banco se não há texto"

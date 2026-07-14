from app.services.document_extractor import _remover_linhas_repetidas


def test_remove_rodape_repetido():
    paginas = [f"RODAPÉ ASSINATURA\nConteúdo único da página {i}" for i in range(10)]
    limpas = _remover_linhas_repetidas(paginas)
    assert all("RODAPÉ ASSINATURA" not in p for p in limpas)
    assert "Conteúdo único da página 3" in limpas[3]


def test_preserva_linhas_nao_repetidas():
    paginas = [f"Cláusula {i} do contrato" for i in range(10)]
    assert _remover_linhas_repetidas(paginas) == paginas


def test_poucas_paginas_nao_remove():
    paginas = ["mesma linha", "mesma linha"]
    assert _remover_linhas_repetidas(paginas) == paginas

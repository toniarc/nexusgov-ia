from app.services.embedding_service import dividir_em_chunks, vetor_para_literal


def test_vetor_para_literal():
    assert vetor_para_literal([0.5, -1.0, 2.25]) == "[0.5,-1.0,2.25]"


def test_chunks_texto_vazio():
    assert dividir_em_chunks("   ", 1500, 80) == []


def test_um_chunk_por_frase():
    texto = (
        "A vigência do contrato será de doze meses contados da assinatura. "
        "O pagamento será efetuado em até trinta dias a contar do atesto na nota fiscal. "
        "A garantia mínima dos serviços será de um ano após o recebimento definitivo."
    )
    chunks = dividir_em_chunks(texto, tamanho_max=1500, tamanho_min=40)
    assert len(chunks) == 3
    assert chunks[0].endswith("contados da assinatura.")
    assert chunks[1].startswith("O pagamento")
    assert chunks[2].startswith("A garantia")


def test_frase_quebrada_em_paginas_vira_um_chunk():
    # Simula frase dividida na virada de página (páginas unidas por espaço no extractor).
    pagina1 = "O valor estimado total para o contrato é de"
    pagina2 = "noventa e três milhões de reais, conforme planilha anexa."
    chunks = dividir_em_chunks(f"{pagina1} {pagina2}", tamanho_max=1500, tamanho_min=40)
    assert len(chunks) == 1
    assert "é de noventa e três milhões" in chunks[0]


def test_fragmento_curto_agrega_a_frase_seguinte():
    texto = "1. OBJETO\n1.1. O presente termo tem por objeto o registro de preços para manutenção predial."
    chunks = dividir_em_chunks(texto, tamanho_max=1500, tamanho_min=40)
    assert len(chunks) == 1
    assert chunks[0].startswith("1. OBJETO 1.1.")


def test_frase_longa_fatia_no_espaco():
    frase = "palavra " * 500  # ~4000 chars sem pontuação
    chunks = dividir_em_chunks(frase, tamanho_max=1000, tamanho_min=80)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert all(not c.startswith("alavra") for c in chunks)  # corte em espaço, não no meio


def test_sobra_curta_final_anexa_ao_ultimo_chunk():
    texto = "Primeira frase completa do documento com tamanho suficiente. Fim."
    chunks = dividir_em_chunks(texto, tamanho_max=1500, tamanho_min=40)
    assert len(chunks) == 1
    assert chunks[0].endswith("Fim.")


def test_linhas_de_planilha_viram_chunks():
    texto = "Vigilante | 12 | R$ 3.500,00\nPorteiro | 8 | R$ 2.900,00\nZelador | 4 | R$ 2.700,00"
    chunks = dividir_em_chunks(texto, tamanho_max=1500, tamanho_min=20)
    assert len(chunks) == 3
    assert chunks[1] == "Porteiro | 8 | R$ 2.900,00"

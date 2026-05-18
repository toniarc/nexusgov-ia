import pytest

from app.services.contract_resolver import extrair_referencia_contrato


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("me mostra o contrato 2024/1", (2024, 1)),
        ("dados do contrato n° 2023/15", (2023, 15)),
        ("Contrato Nº 2025/3 está ativo?", (2025, 3)),
        ("2024/1", (2024, 1)),
        ("2024 / 12", (2024, 12)),
    ],
)
def test_extrai_referencia_valida(texto, esperado):
    assert extrair_referencia_contrato(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "olá tudo bem?",
        "12/2024",
        "1/2",
        "preciso de 3/4 de algo",
        "ano 1899/1",
    ],
)
def test_nao_extrai_referencia(texto):
    assert extrair_referencia_contrato(texto) is None

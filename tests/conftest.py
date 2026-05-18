"""
Fixtures globais.
Integration tests dependem de variáveis em .env.test (gitignored) carregado por pytest-dotenv,
ou exportadas no shell antes de rodar `pytest`.
"""
import os
import pytest


@pytest.fixture(scope="session")
def integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "0") == "1"


@pytest.fixture(scope="session")
def nexusgov_api_url() -> str:
    return os.getenv("NEXUSGOV_API_URL", "http://localhost:8080")

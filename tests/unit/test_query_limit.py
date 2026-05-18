from app.services.query_engine import enforce_limit


def test_adiciona_limit_quando_ausente():
    sql = "SELECT * FROM contrato WHERE id = 1"
    assert enforce_limit(sql).endswith("LIMIT 100")


def test_nao_duplica_limit_existente():
    sql = "SELECT * FROM contrato LIMIT 10"
    assert enforce_limit(sql) == "SELECT * FROM contrato LIMIT 10"


def test_nao_adiciona_em_agregacao():
    sql = "SELECT COUNT(*) FROM contrato"
    assert "LIMIT" not in enforce_limit(sql)


def test_adiciona_em_group_by():
    sql = "SELECT empresa_id, COUNT(*) FROM contrato GROUP BY empresa_id"
    assert enforce_limit(sql).endswith("LIMIT 100")

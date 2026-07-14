import json
from pathlib import Path

_DATASET = Path(__file__).parent.parent / "eval" / "dataset_contrato_exemplo.json"


def _perguntas() -> list[dict]:
    return json.loads(_DATASET.read_text(encoding="utf-8"))["perguntas"]


def test_dataset_tem_20_corretas_e_10_erradas():
    perguntas = _perguntas()
    assert len(perguntas) == 30
    assert sum(1 for p in perguntas if p["tipo"] == "correta") == 20
    assert sum(1 for p in perguntas if p["tipo"] == "errada") == 10


def test_ids_unicos_e_sequenciais():
    ids = [p["id"] for p in _perguntas()]
    assert ids == list(range(1, 31))


def test_campos_obrigatorios():
    for p in _perguntas():
        assert p["pergunta"].strip()
        if p["tipo"] == "correta":
            assert p["resposta_esperada"].strip()
            assert p["keywords_esperadas"], f"#{p['id']} sem keywords"
            assert all(isinstance(g, list) and g for g in p["keywords_esperadas"])
        else:
            assert p["resposta_errada"].strip()
            assert p["keywords_proibidas"], f"#{p['id']} sem keywords proibidas"

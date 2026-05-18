from app.services.markdown_renderer import render


def test_renderiza_negrito():
    assert "<strong>oi</strong>" in render("**oi**")


def test_sanitiza_script():
    out = render("oi <script>alert(1)</script>")
    assert "<script" not in out.lower()


def test_sanitiza_onerror():
    out = render('<img src=x onerror="alert(1)">')
    assert "onerror" not in out.lower()

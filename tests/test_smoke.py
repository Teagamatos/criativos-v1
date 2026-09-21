"""Smoke tests das partes puras (sem rede): python -m tests.test_smoke"""
import os
import tempfile

os.environ["STATE_DB"] = os.path.join(tempfile.mkdtemp(), "state.db")

from app import pipeline, sorteio, state  # noqa: E402
from app.render import montar_html  # noqa: E402

# ── paleta: 4 combinações completas ──────────────────────────
assert len(sorteio.PALETA) == 4
papeis = {"id", "fundo", "texto", "pill_fundo", "pill_texto", "elipse", "card_logo_fundo", "borda_logo_empresa"}
for c in sorteio.PALETA:
    assert papeis <= set(c), f"combinação {c.get('id')} incompleta"
combo = sorteio.sortear_combinacao()
assert combo in sorteio.PALETA
print(f"✓ paleta ok — sorteada: {combo['id']}")

# ── foto: top do pool, pulando as últimas N usadas ────────────
pool = [{"id": f"foto{i}", "url": f"https://images.pexels.com/photos/{i}/foto.jpeg"} for i in range(8)]
usadas = [sorteio.escolher_foto(pool)["id"] for _ in range(5)]
assert usadas == ["foto0", "foto1", "foto2", "foto3", "foto4"], "não pulou as usadas em ordem de relevância"
recentes = state.fotos_recentes(5)
proxima = sorteio.escolher_foto(pool)
assert proxima["id"] not in recentes, "escolheu foto dentro das últimas N"
pool_pequeno = [{"id": "unica", "url": "https://images.pexels.com/photos/1/foto.jpeg"}]
assert sorteio.escolher_foto(pool_pequeno)["id"] == "unica"  # fallback: pool < N não trava
print(f"✓ fotos ok — recentes {sorted(recentes)} excluídas, sorteada: {proxima['id']}")

# ── foto: rosto obrigatório + nota da curadoria ───────────────
rosto_ok = (0.4, 0.3, 0.05, 0.22, 150.0)
pool_cur = [
    {"id": "sem_rosto", "url": "u", "rosto": None},     # nota altíssima, mas sem rosto → não dá pra enquadrar
    {"id": "rosto_ruim", "url": "u", "rosto": rosto_ok},
    {"id": "rosto_bom", "url": "u", "rosto": rosto_ok},
    {"id": "rosto_medio", "url": "u", "rosto": rosto_ok},
]
notas = {"sem_rosto": 10, "rosto_ruim": 0, "rosto_bom": 9, "rosto_medio": 6}
assert sorteio.escolher_foto(pool_cur, notas)["id"] == "rosto_bom", "devia levar a maior nota entre as COM rosto"
assert sorteio.escolher_foto(pool_cur, notas)["id"] == "rosto_medio", "devia pular a recém-usada e ir pra próxima melhor com rosto"
pool_sem_rosto = [{"id": "a", "url": "u", "rosto": None}, {"id": "b", "url": "u", "rosto": None}]
assert sorteio.escolher_foto(pool_sem_rosto, {"a": 0, "b": 5})["id"] == "b", "sem nenhuma com rosto, ainda usa a nota"
print("✓ escolha ok — rosto obrigatório, maior nota vence, fallback sem rosto")


class _Prov:
    def __init__(self, resultados):
        self.resultados = resultados

    def buscar_fotos(self, q):
        r = self.resultados[q]
        if isinstance(r, Exception):
            raise r
        return r


f = lambda i: {"id": str(i), "url": "u"}  # noqa: E731
prov = _Prov({"q1": [f(1), f(2), f(3)], "q2": [f(9), f(2), f(8)], "quebra": RuntimeError("rate limit")})
assert [x["id"] for x in pipeline.buscar_pool(prov, ["q1", "q2"])] == ["1", "9", "2", "3", "8"], "não intercalou/deduplicou"
assert [x["id"] for x in pipeline.buscar_pool(prov, ["quebra", "q1"])] == ["1", "2", "3"], "query que falha devia ser ignorada"
try:
    pipeline.buscar_pool(prov, ["quebra"])
    raise AssertionError("todas as queries falhando devia propagar o erro")
except RuntimeError:
    pass
print("✓ buscar_pool ok — intercala, deduplica e tolera query que falha")

# ── template: placeholders, sigilosa e múltiplas localizações ─
vaga = {
    "titulo": "Consultor de Vendas <Sênior>",  # testa escape
    "localizacoes": ["São Paulo, SP", "Campinas, SP", "Curitiba, PR"],
}
logo = {"url": "https://tfc/logo.png", "largura": 400, "altura": 200}
html = montar_html(vaga, combo, "data:image/png;base64,x", logo, sigilosa=False)
corpo = html[html.find("<body>"):]
assert "{{" not in html, "sobrou placeholder sem preencher"
assert corpo.count('class="pill"') == 3, "faltou pill de localização"
assert "&lt;Sênior&gt;" in html, "cargo não escapado"
assert 'class="arte  ' in corpo and 'sigilosa' not in corpo, "modo normal não deveria ter classe sigilosa"
assert combo["texto"] in html and "https://tfc/logo.png" in html
assert "width:278px;height:139px" in html, "logo devia ser escalada tipo contain (limitada pela largura)"

html_sig = montar_html(vaga, combo, "data:x", logo, sigilosa=True)
assert 'class="arte sigilosa ' in html_sig, "flag sigilosa não aplicou a classe"

html_sem_logo = montar_html(vaga, combo, "data:x", None, sigilosa=False)
assert "sigilosa" in html_sem_logo, "sem logo TFC deveria ocultar o slot"
corpo_sem_logo = html_sem_logo[html_sem_logo.find("<body>"):]
assert "logo-empresa" not in corpo_sem_logo, "sem logo não deveria nem renderizar o slot no body"
print("✓ template ok — escape, pills, sigilosa e fallback sem logo")

print("\nTodos os smoke tests passaram.")

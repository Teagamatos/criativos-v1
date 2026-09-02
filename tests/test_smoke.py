"""Smoke tests das partes puras (sem rede): python -m tests.test_smoke"""
import os
import tempfile

os.environ["STATE_DB"] = os.path.join(tempfile.mkdtemp(), "state.db")

from app import sorteio, state  # noqa: E402
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

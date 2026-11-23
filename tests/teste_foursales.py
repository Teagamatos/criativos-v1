"""Teste local do fluxo Foursales SEM rede nem ClickUp: python -m tests.teste_foursales [foto.jpg ...]

- valida as regras de texto (título, localização, modelo, segmento);
- monta capa + PDF com fotos locais (rosto detectado com o mesmo código da API)
  e salva em tests/payloads/foursales-*.pdf;
- simula o pipeline com ClickUp/busca de foto substituídos, pra conferir o
  comentário de campo faltante.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("STATE_DB", os.path.join(tempfile.mkdtemp(), "state.db"))

import cv2  # noqa: E402

from app import rosto  # noqa: E402
from app.foursales import capa, pipeline, render, textos  # noqa: E402

OUT = Path(__file__).parent / "payloads"

# ── textos ────────────────────────────────────────────────────
assert textos.limpar_titulo("Gerente Marketing - Biguaçu (SC)", ["Biguaçu, SC"]) == "Gerente Marketing"
assert textos.limpar_titulo("Executivo(a) de Vendas B2B | Porto Alegre (RS)", ["Porto Alegre, RS"]) == "Executivo(a) de Vendas B2B"
assert textos.limpar_titulo("Gerente Regional de Vendas | SP", ["São Paulo, SP"]) == "Gerente Regional de Vendas"
assert textos.limpar_titulo("Gerente de Vendas - Papel e Celulose", ["São Paulo, SP"]) == "Gerente de Vendas - Papel e Celulose"
assert textos.formatar_localizacao("Taubaté | SP") == "Taubaté, SP"
assert textos.formatar_localizacao("Curitiba (PR)") == "Curitiba, PR"
assert textos.formatar_localizacao("Porto Alegre, RS") == "Porto Alegre, RS"
assert textos.formatar_localizacao("Remoto") == "Remoto"
assert textos.formatar_modelo("Híbrido") == "Modelo Híbrido"
assert textos.formatar_modelo("") is None
assert textos.segmento_curto_local("Logistica, Transporte e Armazenagem") == "Logistica"
assert textos.segmento_curto_local("Bens de Consumo") == "Bens de Consumo"
assert textos.segmento_curto_local("Distribuidora de equipamentos Técnicos do segmento Agropecuário e industrial.") == "Distribuidora de equipamentos"
print("✓ textos ok")

assert pipeline.faltantes({"cargo": "x", "segmento": "y", "localizacoes": ["a"], "desafio": "d"}) == []
assert pipeline.faltantes({"cargo": "x", "localizacoes": [], "desafio": ""}) == ["segmento", "localização", "desafio"]
print("✓ obrigatórios ok")


async def _browser_local():
    """No container de teste o Chromium do Playwright pode não estar instalado."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    exe = os.environ.get("CHROME_PATH")
    return await pw.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else await pw.chromium.launch()

if os.environ.get("CHROME_PATH"):
    _b = None

    async def _get():
        global _b
        if _b is None:
            _b = await _browser_local()
        return _b

    render._get_browser = _get  # type: ignore[assignment]

VAGA = {
    "titulo": "Head de Vendas",
    "segmento": "Saúde",
    "localizacoes": ["São Paulo, SP"],
    "modelo": "Modelo Híbrido",
    "desafio": "Buscamos Head de Vendas para liderar sua operação comercial. O profissional será responsável pela "
    "estruturação da máquina de crescimento, desenvolvimento da equipe e aumento das vendas.",
}


async def gerar_local(fotos: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    for i, caminho in enumerate(fotos):
        dados = Path(caminho).read_bytes()
        img = cv2.imdecode(__import__("numpy").frombuffer(dados, "uint8"), cv2.IMREAD_GRAYSCALE)
        r = rosto._detectar(cv2.resize(img, (800, round(800 * img.shape[0] / img.shape[1]))))
        if r is None:
            print(f"  {caminho}: sem rosto detectado, pulando")
            continue
        uri = capa.montar(dados, r)
        vaga = dict(VAGA, modelo=None if i % 2 else VAGA["modelo"])  # alterna: com e sem modelo
        pdf, ajustes = await render.render_pdf(render.montar_html(vaga, uri))
        destino = OUT / f"foursales-{Path(caminho).stem}.pdf"
        destino.write_bytes(pdf)
        print(f"✓ {destino.name}: {len(pdf) // 1024} KB, ajustes {ajustes}")


async def faltando() -> None:
    comentarios = []

    async def comentar(task, texto):
        comentarios.append(texto)

    pipeline.clickup.post_comment = comentar  # type: ignore[assignment]
    await pipeline.processar({"task": "t1", "cargo": "Head", "localizacoes": ["SP"]})
    assert comentarios and "falta segmento, desafio" in comentarios[0], comentarios
    print("✓ campo faltante vira comentário no card:", comentarios[0])


if __name__ == "__main__":
    asyncio.run(faltando())
    if len(sys.argv) > 1:
        asyncio.run(gerar_local(sys.argv[1:]))
    print("\nTeste Foursales ok.")

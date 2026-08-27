"""Testa o pipeline completo (menos ClickUp) a partir de um payload real do /generate.

Uso:
    python -m tests.teste_payload payload.json
    cat payload.json | python -m tests.teste_payload -

Não anexa nem comenta no ClickUp — só salva o PNG em _teste_fotos/.
"""
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

from app import logo, openai_client, pexels, render, rosto, sorteio

SAIDA_DIR = Path(__file__).resolve().parent.parent / "_teste_fotos"


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


async def gerar(dados: dict) -> Path:
    vaga = {
        "titulo": dados["cargo"],
        "segmento": dados.get("segmento") or "",
        "nivel": dados.get("nivel") or "",
        "empresa": dados.get("empresa") or "",
        "localizacoes": dados["localizacoes"],
    }
    sigilosa = bool(dados.get("sigilosa"))

    logo_empresa = None
    if not sigilosa:
        logo_empresa = await asyncio.to_thread(logo.baixar_png, dados.get("logo"))
        print(f"logo: {'OK' if logo_empresa else 'falhou/ausente'}")

    combinacao = sorteio.sortear_combinacao()
    contexto = {"segmento": vaga["segmento"], "empresa": vaga["empresa"], "nivel": vaga["nivel"]}
    query = await openai_client.gerar_query_foto(vaga["titulo"], contexto) or f"{vaga['titulo']} portrait"
    print(f"query Pexels: {query!r}")

    pool = await asyncio.to_thread(pexels.buscar_fotos, query)
    if not pool:
        raise SystemExit(f"Pexels não retornou nenhuma foto pra query {query!r}")
    pool = await asyncio.to_thread(rosto.ordenar_por_rosto, pool)
    foto = sorteio.escolher_foto(pool)
    print(f"foto escolhida: {foto['id']} - rosto detectado: {foto.get('rosto') is not None}")
    foto_uri = await asyncio.to_thread(rosto.enquadrar, foto, combinacao["elipse"])

    html = render.montar_html(vaga, combinacao, foto_uri, logo_empresa, sigilosa)
    png = await render.render_png(html)
    await render.close_browser()

    SAIDA_DIR.mkdir(exist_ok=True)
    sufixo = "_sigilosa" if sigilosa else ""
    destino = SAIDA_DIR / f"teste_{dados['task']}_{_slug(vaga['titulo'])}{sufixo}.png"
    destino.write_bytes(png)
    return destino


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("uso: python -m tests.teste_payload <arquivo.json | ->")
    raw = sys.stdin.read() if sys.argv[1] == "-" else Path(sys.argv[1]).read_text(encoding="utf-8")
    payload = json.loads(raw)
    dados = payload[0] if isinstance(payload, list) else payload

    destino = asyncio.run(gerar(dados))
    print(f"OK - salvo em {destino} (NAO enviado ao ClickUp)")


if __name__ == "__main__":
    main()

"""Gera uma arte de teste ponta-a-ponta (GPT → Pexels → rosto → render) pra um
cargo qualquer, sem precisar de card no ClickUp nem da Foursales.

Uso:
    python -m tests.teste_foto_cargo "Padeiro"
    python -m tests.teste_foto_cargo "Engenheiro de Desenvolvimento de Mercado" \
        --segmento "Agronegócio" --empresa "AgroCorp" --nivel Pleno \
        --localizacoes "São Paulo, SP" "Campinas, SP" --sigilosa

Salva em _teste_fotos/teste_<slug-do-cargo>.png (mesmo padrão dos PNGs já
existentes na pasta).
"""
import argparse
import asyncio
import re
import unicodedata
from pathlib import Path

from app import openai_client, pexels, render, rosto, sorteio

SAIDA_DIR = Path(__file__).resolve().parent.parent / "_teste_fotos"


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


async def gerar(cargo: str, segmento: str, empresa: str, nivel: str, localizacoes: list[str], sigilosa: bool) -> Path:
    combinacao = sorteio.sortear_combinacao()
    contexto = {"segmento": segmento, "empresa": empresa, "nivel": nivel}

    query = await openai_client.gerar_query_foto(cargo, contexto) or f"{cargo} portrait"
    print(f"query Pexels: {query!r}")

    pool = await asyncio.to_thread(pexels.buscar_fotos, query)
    if not pool:
        raise SystemExit(f"Pexels nao retornou nenhuma foto pra query {query!r}")
    pool = await asyncio.to_thread(rosto.ordenar_por_rosto, pool)
    foto = sorteio.escolher_foto(pool)
    print(f"foto escolhida: {foto['id']} - rosto detectado: {foto.get('rosto') is not None}")
    foto_uri = await asyncio.to_thread(rosto.enquadrar, foto, combinacao["elipse"])

    vaga = {"titulo": cargo, "localizacoes": localizacoes or ["São Paulo, SP"]}
    html = render.montar_html(vaga, combinacao, foto_uri, "https://placehold.co/200x80" if not sigilosa else None, sigilosa)
    png = await render.render_png(html)
    await render.close_browser()

    SAIDA_DIR.mkdir(exist_ok=True)
    destino = SAIDA_DIR / f"teste_{_slug(cargo)}.png"
    destino.write_bytes(png)
    return destino


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cargo", help="título do cargo, ex.: 'Padeiro'")
    ap.add_argument("--segmento", default="", help="segmento da empresa (contexto pra query do GPT)")
    ap.add_argument("--empresa", default="", help="nome da empresa (contexto pra query do GPT)")
    ap.add_argument("--nivel", default="", help="nível da vaga (contexto pra query do GPT)")
    ap.add_argument("--localizacoes", nargs="*", default=[], help="uma ou mais localizações, ex.: --localizacoes 'São Paulo, SP' 'Curitiba, PR'")
    ap.add_argument("--sigilosa", action="store_true", help="simula vaga sigilosa (sem logo/nome da empresa)")
    args = ap.parse_args()

    destino = asyncio.run(gerar(args.cargo, args.segmento, args.empresa, args.nivel, args.localizacoes, args.sigilosa))
    print(f"OK - salvo em {destino}")


if __name__ == "__main__":
    main()

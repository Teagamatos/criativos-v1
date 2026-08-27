"""Busca de fotos via Pexels API — substitui o pool fixo do Google Drive.

A query de busca (em inglês) vem do GPT (openai_client.gerar_query_foto),
gerada a partir do cargo + contexto da vaga. Os resultados já são URLs
públicas do CDN da Pexels — sem credencial necessária no Chromium do render,
diferente do Drive (que exigia baixar o binário e embutir como data URI).
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config

_URL = "https://api.pexels.com/v1/search"
_RETRY = dict(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)


@retry(**_RETRY)
def buscar_fotos(query: str, per_page: int = 20) -> list[dict]:
    """Retorna [{'id', 'url', 'thumb'}, ...] para a query dada (orientação retrato).

    'url' (large2x) é a foto final usada no render; 'thumb' (medium, menor e
    mais rápida de baixar) é usada só pra detecção de rosto (rosto.py).
    """
    r = httpx.get(
        _URL,
        headers={"Authorization": config.PEXELS_API_KEY},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=15,
    )
    r.raise_for_status()
    fotos = r.json().get("photos", [])
    return [{"id": str(f["id"]), "url": f["src"]["large2x"], "thumb": f["src"]["medium"]} for f in fotos]

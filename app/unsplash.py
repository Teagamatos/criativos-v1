"""Busca de fotos via Unsplash API — alternativa em teste ao Pexels (pexels.py).

Mesma interface de app/pexels.py (buscar_fotos → [{'id', 'url', 'thumb'}, ...])
pra poder ser trocada por config.FOTO_PROVIDER sem tocar no resto do pipeline.
"""
import logging

import httpx
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from . import config

log = logging.getLogger("unsplash")

_URL = "https://api.unsplash.com/search/photos"
_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)


@retry(**_RETRY)
def buscar_fotos(query: str, per_page: int = 20) -> list[dict]:
    """Retorna [{'id', 'url', 'thumb'}, ...] para a query dada (orientação retrato).

    'url' (regular) é a foto final usada no render; 'thumb' (small, menor e
    mais rápida de baixar) é usada só pra detecção de rosto (rosto.py).
    """
    r = httpx.get(
        _URL,
        headers={"Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}"},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=15,
    )
    r.raise_for_status()
    fotos = r.json().get("results", [])
    return [{"id": str(f["id"]), "url": f["urls"]["regular"], "thumb": f["urls"]["small"]} for f in fotos]

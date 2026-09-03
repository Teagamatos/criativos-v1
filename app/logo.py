"""Logo da contratante — vem pronto no payload de entrada (URL assinada do S3).

A URL chega SEM extensão de arquivo (query string de assinatura no lugar) —
em vez de confiar no Content-Type que o S3 devolve, baixamos os bytes,
decodificamos com OpenCV (que identifica o formato pelos bytes, não pela URL)
e reencodamos explicitamente como PNG. Isso garante que o Chromium do render
sempre recebe uma imagem com formato reconhecível, não importa o que a URL
original tinha.
"""
import base64
import logging

import cv2
import httpx
import numpy as np
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

log = logging.getLogger("logo")

_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=False,
)


@retry(**_RETRY)
def _baixar(url: str) -> bytes:
    r = httpx.get(url, timeout=15)
    r.raise_for_status()
    return r.content


def baixar_png(url: str | None) -> dict | None:
    """Baixa e converte a logo para data URI PNG.

    Devolve {'url': data_uri, 'largura': int, 'altura': int} — as dimensões
    reais (pós-decode) permitem ao template desenhar a moldura (fundo/borda/
    sombra) exatamente no contorno da logo, sem letterboxing.

    Falha ao baixar/decodificar (URL expirada, formato inválido, etc.) devolve
    None — a arte sai sem logo (mesmo modo "sigilosa" visualmente), sem
    interromper a geração.
    """
    if not url:
        return None
    try:
        conteudo = _baixar(url)
        arr = np.frombuffer(conteudo, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            log.error("logo baixada mas não decodificada (formato desconhecido)")
            return None
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            return None
        altura, largura = img.shape[:2]
        data_uri = "data:image/png;base64," + base64.b64encode(buf).decode()
        return {"url": data_uri, "largura": largura, "altura": altura}
    except Exception:
        log.exception("falha ao baixar/converter logo")
        return None

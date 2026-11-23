"""Escolha da foto da capa Foursales.

Reaproveita a busca do Salesjobs (Pexels + Unsplash, queries por GPT, curadoria
por visão, exclusão das últimas N usadas), com critérios próprios da capa:
- uma pessoa, rosto detectado, foto COLORIDA;
- espaço acima da cabeça (o template corta a foto no topo da página);
- enquadramento que cubra a capa inteira sem o rosto ficar gigante.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from .. import rosto

log = logging.getLogger("foursales.foto")

# Geometria da capa (px da capa 2200×2731, mesma proporção do frame do Figma)
CAPA_W, CAPA_H = 2200, 2731
ALVO_CX, ALVO_CY = 1600, 520      # centro do rosto (como o homem do template)
ALVO_LARGURA = 330                # largura do rosto (caixa do Haar)
LARGURA_MAX = ALVO_LARGURA * 1.7  # acima disso é close-up demais pra capa
SATURACAO_MIN = 0.10              # abaixo disso a foto é P&B/sem cor

INSTRUCOES_QUERIES = """Você escolhe fotos de banco de imagens (Pexels/Unsplash) para a capa de divulgação de uma vaga EXECUTIVA (Foursales: gerentes, heads, diretores, executivos de vendas e marketing).

Escreva DUAS queries de busca em INGLÊS (3 a 6 palavras cada). Cada uma descreve UMA pessoa sozinha, em retrato vertical da cintura para cima, roupa social (terno, blazer), olhando para a câmera, em ambiente corporativo.
- Query 1: executivo + cenário coerente com o segmento da empresa, sem virar operário (ex.: "business executive portrait modern office", "executive woman portrait warehouse office").
- Query 2: genérica e segura (ex.: "confident executive portrait suit").
- Sempre inclua "portrait". Nunca use team, meeting, group, hands, back view, silhouette, worker, factory.

Responda APENAS com JSON válido: {"queries": ["<query 1>", "<query 2>"]}"""

INSTRUCOES_CURADORIA = """Você faz a curadoria de fotos para a CAPA de divulgação de uma vaga executiva (Foursales). A foto ocupa a metade direita de uma capa vertical azul-marinho; o rosto fica no terço superior, à direita do título.

Dê a cada foto uma nota inteira de 0 a 10.

NOTA 0 (eliminatória) se qualquer um for verdade:
- não há UMA pessoa como assunto principal, ou há mais de uma em destaque;
- rosto não visível (de costas, perfil extremo, cortado) ou cabeça cortada no topo da foto;
- foto em preto e branco ou com filtro forte;
- roupa informal demais para executivo (jeans, moletom, camiseta, gola alta casual) ou uniforme de obra/fábrica;
- logo, marca, crachá ou texto legível na roupa ou no fundo; marca d'água;
- cigarro, bebida, arma, aparência degradada, foto desfocada ou caricata.

Nas demais, pontue por: parecer um executivo sênior (terno/blazer, postura confiante), rosto nítido olhando para a câmera ou levemente para a direita, espaço acima da cabeça, fundo corporativo limpo e iluminação boa.

Responda APENAS com JSON válido: {"notas": {"<id>": <nota>}} incluindo todas as fotos recebidas."""


def plano(r: rosto.Rosto, largura_src: int, altura_src: int) -> tuple[float, float]:
    """(escala, largura final do rosto) pra pôr o rosto no alvo cobrindo a capa toda."""
    fx, fy = r.cx * largura_src, r.cy * altura_src
    escala = max(
        ALVO_LARGURA / (r.largura * largura_src),
        ALVO_CX / max(fx, 1),
        (CAPA_W - ALVO_CX) / max(largura_src - fx, 1),
        ALVO_CY / max(fy, 1),
        (CAPA_H - ALVO_CY) / max(altura_src - fy, 1),
    )
    return escala, r.largura * largura_src * escala


def _saturacao(dados: bytes) -> float:
    img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return 0.0
    return float(cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1].mean() / 255)


def _analisar(foto: dict) -> dict:
    """Rosto + cor + enquadramento. Foto que não serve fica com rosto=None."""
    try:
        dados = rosto._baixar_bytes(foto.get("thumb") or foto["url"])
        img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_GRAYSCALE)
        r = rosto._detectar(img)
        motivo = None
        if r is None or r.area < rosto._AREA_MIN:
            motivo, r = "sem rosto", None
        else:
            h, w = img.shape
            topo_cabeca = r.cy - (r.largura * w / h) * 0.9  # fração da altura
            _, largura_final = plano(r, w, h)
            if topo_cabeca < 0.03:
                motivo = "cabeça encostada no topo"
            elif largura_final > LARGURA_MAX:
                motivo = "close-up demais"
            elif _saturacao(dados) < SATURACAO_MIN:
                motivo = "sem cor"
            if motivo:
                r = None
    except Exception:
        dados, r, motivo = None, None, "falha ao baixar"
    return {**foto, "rosto": r, "thumb_bytes": dados, "descarte": motivo}


def analisar(pool: list[dict]) -> list[dict]:
    """Aprovadas primeiro (maior rosto antes), depois as descartadas."""
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(_analisar, pool))
    ok = sorted((f for f in res if f["rosto"]), key=lambda f: f["rosto"].area, reverse=True)
    descartes = {}
    for f in res:
        if not f["rosto"]:
            descartes[f["descarte"]] = descartes.get(f["descarte"], 0) + 1
    log.info("fotos aprovadas: %d de %d — descartes: %s", len(ok), len(res), descartes)
    return ok + [f for f in res if not f["rosto"]]


def candidatas_curadoria(pool: list[dict]) -> list[dict]:
    return [f for f in pool if f.get("rosto") and f.get("thumb_bytes")][:16]

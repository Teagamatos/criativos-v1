"""Escolhe e reenquadra a foto do Pexels pra deixar o rosto sempre visível.

A busca por palavra-chave não garante que o topo do resultado seja de fato
um retrato de rosto fechado — baixamos as miniaturas dos candidatos e rodamos
detecção de rosto local (OpenCV, sem custo de API) pra escolher entre eles
(`ordenar_por_rosto`) e depois recompor a foto vencedora (`enquadrar`) pra
garantir que o rosto caia numa posição boa do recorte, não só torcer pra
calhar.

Geometria real do template (template-salesjobs.html): a foto entra num
container CIRCULAR de 1033×1033 (.foto-circulo) com object-fit:cover +
object-position:"center top". Fotos de banco em retrato (mais estreitas que
o container) preenchem 100% da LARGURA — ou seja, a fração horizontal do
rosto na foto original é preservada 1:1 (o container é quadrado, então as
frações x e y mapeiam direto, sem distorcer) — e é por isso que
object-position no eixo X NÃO tem efeito nenhum aqui: o cover já usa toda a
largura, não sobra folga horizontal pra "empurrar" a imagem (testado
empiricamente: "left top" e "center top" dão o mesmo resultado pixel a
pixel). Por cima da foto tem uma ELIPSE de acento (.elipse) CONCÊNTRICA —
mesmo centro do .foto-circulo, raio menor (255.5 de 516.5, ou seja, ~24.7%
da largura do container) — criando um anel de largura constante em vez de
uma faixa só de um lado.

Como o CSS não consegue reposicionar horizontalmente, `enquadrar` faz isso
no servidor: recorta/reamostra a foto (Python/OpenCV) já centrada no ponto
certo do anel, preenchendo com a cor da elipse (`combinacao["elipse"]`)
onde não sobrar foto de verdade — essa sobra de preenchimento cai quase
toda debaixo da própria elipse, então normalmente nem aparece.
"""
import base64
import logging

import cv2
import httpx
import numpy as np
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

log = logging.getLogger("rosto")

_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_RETRY = dict(
    stop=stop_after_attempt(2),
    wait=wait_exponential(min=1, max=4),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=False,
)


@retry(**_RETRY)
def _baixar(url: str, cor: int) -> np.ndarray:
    r = httpx.get(url, timeout=12)
    r.raise_for_status()
    arr = np.frombuffer(r.content, dtype=np.uint8)
    return cv2.imdecode(arr, cor)


# Zona segura na foto ORIGINAL (frações 0-1 do container 1033×1033),
# derivada da geometria concêntrica do template — ver docstring acima.
_RAIO_ELIPSE = 0.247  # 255.5px / 1033px — dentro disso do centro, a elipse cobre
_Y_MIN_SEGURO = 0.14  # acima disso (~139px/1033px), fica fora do canvas por cima
_X_MAX_SEGURO = 0.57  # além disso (~594px/1033px), sai do canvas pela direita


def _detectar(img: np.ndarray | None) -> tuple[float, float, float] | None:
    """Retorna (cx_relativo, cy_relativo, area_relativa) do maior rosto
    detectado, ou None se não achou nenhum.

    Quando há mais de um candidato (ex.: estampa numa roupa parecendo rosto),
    escolhe pelo PESO de confiança do Haar cascade (`outputRejectLevels`), não
    pela maior área — um falso positivo pode ser maior em pixels e ainda
    assim ter confiança bem menor que o rosto de verdade.
    """
    if img is None:
        return None
    altura, largura = img.shape
    lado_min = int(min(altura, largura) * 0.12)
    faces, _niveis, pesos = _CASCADE.detectMultiScale3(
        img, scaleFactor=1.1, minNeighbors=5, minSize=(lado_min, lado_min), outputRejectLevels=True
    )
    if len(faces) == 0:
        return None
    x, y, w, h = faces[int(np.argmax(pesos))]
    area_relativa = (w * h) / (largura * altura)
    cx_relativo = (x + w / 2) / largura
    cy_relativo = (y + h / 2) / altura
    return cx_relativo, cy_relativo, area_relativa


def _pontuar(pos: tuple[float, float, float] | None) -> float:
    """0 = sem rosto detectado. Maior = rosto grande, fora do círculo da
    elipse e dentro da área visível no canvas."""
    if pos is None:
        return 0.0
    cx_relativo, cy_relativo, area_relativa = pos

    distancia_centro = ((cx_relativo - 0.5) ** 2 + (cy_relativo - 0.5) ** 2) ** 0.5
    peso_elipse = max(0.0, min(1.0, (distancia_centro - _RAIO_ELIPSE) / 0.15))

    peso_y = 1.0
    if cy_relativo < _Y_MIN_SEGURO:
        peso_y = max(0.0, 1 - (_Y_MIN_SEGURO - cy_relativo) / 0.1)
    peso_x = 1.0
    if cx_relativo > _X_MAX_SEGURO:
        peso_x = max(0.0, 1 - (cx_relativo - _X_MAX_SEGURO) / 0.15)

    return area_relativa * peso_elipse * peso_x * peso_y


def ordenar_por_rosto(pool: list[dict]) -> list[dict]:
    """Recebe [{'id', 'url', 'thumb'}, ...] e devolve reordenado: rosto melhor
    enquadrado primeiro. Cada item ganha a chave 'rosto' com
    (cx_relativo, cy_relativo, area_relativa) do maior rosto detectado, ou
    None se não achou nenhum — usado depois por `enquadrar`. Falha ao
    baixar/decodificar uma foto = pontuação 0 (não interrompe a geração, só
    perde prioridade). Ordem estável entre empates, então quem não tem rosto
    detectado mantém a ordem de relevância original do Pexels.
    """
    pontuados = []
    for foto in pool:
        try:
            img = _baixar(foto.get("thumb") or foto["url"], cv2.IMREAD_GRAYSCALE)
        except Exception:
            img = None
        pos = _detectar(img)
        pontuados.append(({**foto, "rosto": pos}, _pontuar(pos)))
    pontuados.sort(key=lambda par: par[1], reverse=True)
    return [foto for foto, _ in pontuados]


# Alvo do centro do rosto dentro do container 1033×1033 — terço superior
# esquerdo do anel visível (fora do círculo da elipse, com margem).
_ALVO_X = 140
_ALVO_Y = 280
_CONTAINER = 1033


def _hex_para_bgr(cor_hex: str) -> tuple[int, int, int]:
    cor_hex = cor_hex.lstrip("#")
    r, g, b = int(cor_hex[0:2], 16), int(cor_hex[2:4], 16), int(cor_hex[4:6], 16)
    return b, g, r


def enquadrar(foto: dict, cor_elipse_hex: str) -> str:
    """Recorta/reamostra a foto escolhida pra deixar o rosto no terço
    superior esquerdo do anel visível. Sem rosto detectado (foto['rosto'] is
    None) ou em qualquer erro, devolve a URL original sem modificar — mesmo
    comportamento de antes, sem interromper a geração.
    """
    pos = foto.get("rosto")
    if pos is None:
        return foto["url"]
    try:
        img = _baixar(foto["url"], cv2.IMREAD_COLOR)
        altura_src, largura_src = img.shape[:2]
        escala = _CONTAINER / largura_src
        altura_esc = round(altura_src * escala)
        img_esc = cv2.resize(img, (_CONTAINER, altura_esc), interpolation=cv2.INTER_AREA)

        cx_relativo, cy_relativo, _ = pos
        face_cx = cx_relativo * _CONTAINER
        face_cy = cy_relativo * altura_esc
        crop_x = round(face_cx - _ALVO_X)
        crop_y = round(face_cy - _ALVO_Y)

        canvas = np.full((_CONTAINER, _CONTAINER, 3), _hex_para_bgr(cor_elipse_hex), dtype=np.uint8)
        src_x0, src_y0 = max(0, crop_x), max(0, crop_y)
        src_x1, src_y1 = min(_CONTAINER, crop_x + _CONTAINER), min(altura_esc, crop_y + _CONTAINER)
        if src_x1 > src_x0 and src_y1 > src_y0:
            dst_x0, dst_y0 = src_x0 - crop_x, src_y0 - crop_y
            canvas[dst_y0 : dst_y0 + (src_y1 - src_y0), dst_x0 : dst_x0 + (src_x1 - src_x0)] = img_esc[
                src_y0:src_y1, src_x0:src_x1
            ]

        ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return foto["url"]
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    except Exception:
        return foto["url"]
